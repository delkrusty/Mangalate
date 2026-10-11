package app.mangalate.local

import android.content.Context
import com.google.mlkit.common.MlKit

/** Inicialização idempotente para uso no leitor e na preparação offline. */
object MlKitSupport {
    @Volatile
    private var ready = false

    fun initialize(context: Context) {
        if (ready) return
        synchronized(this) {
            if (ready) return
            MlKit.initialize(context.applicationContext)
            ready = true
        }
    }
}
