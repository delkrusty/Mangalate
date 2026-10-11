package app.mangalate.local

import android.graphics.Rect
import com.google.android.gms.tasks.Task
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Um bloco de texto da página: área dos caracteres originais + texto + tradução.
 */
data class TextRegion(
    val rect: Rect,
    val original: String,
    val translation: String = "",
    /** Texto sobre a arte (onomatopeia/legenda sem balão). */
    val overArt: Boolean = false,
    /** Texto original escrito na vertical (japonês/chinês). */
    val vertical: Boolean = false,
)

internal suspend fun <T> Task<T>.awaitTask(): T = suspendCancellableCoroutine { cont ->
    addOnSuccessListener { cont.resume(it) }
    addOnFailureListener { cont.resumeWithException(it) }
    addOnCanceledListener { cont.cancel() }
}
