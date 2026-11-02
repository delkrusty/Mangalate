package app.mangalate.local

import java.io.IOException

/** Erro com mensagem pronta para quem lê, mostrada como está no aviso do app. */
class FriendlyException(message: String) : IOException(message)
