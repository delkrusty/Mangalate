package app.mangalate.ui

import android.widget.Toast
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import app.mangalate.translate.MangalatePairing
import app.mangalate.translate.MangalateTranslator
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning

/**
 * "Ler QR code do PC": lê o código que o `parear.py` mostra no computador e preenche
 * endereço e Chave Mangalate. A câmera é aberta pelo Google Play, sem permissão do app.
 */
@Composable
fun MangalatePairingButton(onPaired: (MangalatePairing.Pairing) -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    OutlinedButton(
        modifier = modifier,
        onClick = {
            val options = GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
            GmsBarcodeScanning.getClient(context, options).startScan()
                .addOnSuccessListener { code ->
                    val pairing = MangalatePairing.parse(code.rawValue)
                    if (pairing == null) {
                        Toast.makeText(
                            context,
                            "Esse QR code não é do Mangalate. No computador, rode py parear.py na pasta server.",
                            Toast.LENGTH_LONG,
                        ).show()
                        return@addOnSuccessListener
                    }
                    MangalateTranslator.updateSettings(context) {
                        it.copy(serverUrl = pairing.url, accessKey = pairing.key)
                    }
                    onPaired(pairing)
                }
                .addOnFailureListener {
                    Toast.makeText(
                        context,
                        "Não foi possível abrir o leitor de QR code. Digite o endereço e a chave.",
                        Toast.LENGTH_LONG,
                    ).show()
                }
        },
    ) { Text("Ler QR code do PC") }
}
