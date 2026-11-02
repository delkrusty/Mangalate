package app.mangalate.translate

import android.content.Context
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * O que a pessoa corrige ou aponta no leitor e vai para o servidor: o glossário da obra
 * (nomes e termos) e o "Reportar esta página", que fica salvo no computador.
 */
object MangalateServerLoop {

    /** Um nome ou termo da obra: como está escrito no original e como sai na tradução. */
    data class Term(val source: String, val target: String, val gender: String? = null)

    private fun call(s: MangalateSettings, request: Request.Builder): String {
        MangalateTranslator.authHeaders(s).forEach { (k, v) -> request.header(k, v) }
        return MangalateTranslator.client.newBuilder()
            .callTimeout(60, TimeUnit.SECONDS)
            .build()
            .newCall(request.build())
            .execute()
            .use { response ->
                val text = response.body.string()
                if (!response.isSuccessful) {
                    throw IOException(
                        when (response.code) {
                            401, 403 -> "Chave Mangalate recusada pelo servidor."
                            404 -> "O servidor ainda não tem essa função. Atualize com py rebuild.py no computador."
                            503 -> "O motor ainda está iniciando ou parou. Aguarde e tente de novo."
                            507 -> "O computador não conseguiu salvar. Confira o espaço em disco."
                            else -> "O servidor respondeu ${response.code}."
                        },
                    )
                }
                text
            }
    }

    suspend fun glossary(s: MangalateSettings, work: String): List<Term> = withContext(Dispatchers.IO) {
        val url = (s.normalizedUrl + "/v1/glossary").toHttpUrl().newBuilder().addQueryParameter("obra", work).build()
        parseTerms(JSONObject(call(s, Request.Builder().url(url))).optJSONArray("termos"))
    }

    /** Manda só o que a pessoa escreveu ([terms]) e o que apagou ([removed]); o resto fica como está. */
    suspend fun saveGlossary(s: MangalateSettings, work: String, terms: List<Term>, removed: List<String>): List<Term> =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("obra", work)
                .put(
                    "termos",
                    JSONArray(
                        terms.map { t ->
                            JSONObject().put("source", t.source).put("target", t.target)
                                .apply { if (t.gender != null) put("gender", t.gender) }
                        },
                    ),
                )
                .put("removidos", JSONArray(removed))
                .toString()
                .toRequestBody("application/json".toMediaType())
            val request = Request.Builder().url(s.normalizedUrl + "/v1/glossary").put(body)
            parseTerms(JSONObject(call(s, request)).optJSONArray("termos"))
        }

    private fun parseTerms(array: JSONArray?): List<Term> = (0 until (array?.length() ?: 0)).mapNotNull { i ->
        val item = array!!.optJSONObject(i) ?: return@mapNotNull null
        Term(
            item.optString("source"),
            item.optString("target"),
            item.optString("gender").takeIf { it == "m" || it == "f" },
        ).takeIf { it.source.isNotBlank() }
    }

    /**
     * Manda o original e a tradução desta página, com a nota opcional, para a pasta de
     * relatórios no computador do servidor. Retorna o nome da pasta criada lá. A tradução vem só
     * da que ficou guardada: reportar nunca traduz de novo nem gasta a cota das IAs, e uma página
     * que falhou vai só com o original.
     */
    suspend fun report(context: Context, page: ReaderPage, note: String): String = withContext(Dispatchers.IO) {
        val s = MangalateTranslator.settings.value
        val stream = page.stream ?: throw IOException("A página ainda não carregou.")
        val original = stream().use { it.readBytes() }
        val translated = MangalateTranslator.cached(
            context,
            original,
            sourceLanguage = MangalateWork.language(context, MangalateWork.mangaIdOf(page)),
        )
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("original", "original", original.toRequestBody("application/octet-stream".toMediaType()))
            .apply {
                translated?.let {
                    addFormDataPart("traduzida", "traduzida", it.toRequestBody("application/octet-stream".toMediaType()))
                }
            }
            .apply { MangalateWork.of(page)?.let { addFormDataPart("work", it.toJson()) } }
            .apply { if (note.isNotBlank()) addFormDataPart("nota", note.take(500)) }
            .build()
        val request = Request.Builder().url(s.normalizedUrl + "/v1/report").post(body)
        JSONObject(call(s, request)).optString("pasta")
    }
}
