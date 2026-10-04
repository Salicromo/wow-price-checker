package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * El interruptor de avisos: pausar o reanudar lo que se manda a Discord.
 *
 * Igual que los topes, la app no escribe config.yaml: abre una issue
 * "Avisos: pausar" o "Avisos: reanudar" y el workflow avisos.yml la aplica.
 * Asi el token sigue sin permiso de escritura sobre el codigo.
 *
 * El estado de verdad es la linea `avisos_pausados:` de config.yaml, que se
 * lee en cada descarga. Mientras el workflow no la cambia, lo pedido queda como
 * pendiente, para que el interruptor no vuelva atras nada mas tocarlo.
 */
object Avisos {

    private const val PREFS = "cobertura"
    private const val CLAVE_REAL = "avisos_pausados"
    private const val CLAVE_PENDIENTE = "avisos_pendiente"
    private const val CLAVE_MOTIVO = "avisos_motivo"

    /**
     * Cuanto se cree un pendiente. El workflow tarda un minuto en aplicarlo;
     * si a la media hora config.yaml sigue sin reflejarlo es que algo fallo, y
     * vale mas ensenar lo que dice config.yaml que un pendiente eterno.
     */
    private const val CADUCIDAD_MS = 30 * 60 * 1000L

    private val LINEA = Regex("""(?m)^\s+avisos_pausados:\s*(true|false)\b""")

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Lo que dice config.yaml en la ultima descarga. Sin la linea, activos. */
    fun pausadosEnConfig(texto: String): Boolean =
        LINEA.find(texto)?.groupValues?.get(1) == "true"

    /** Apunta el estado de verdad y olvida el pendiente si ya coincide. */
    fun apuntarConfig(context: Context, config: String) {
        val real = pausadosEnConfig(config)
        val editor = prefs(context).edit().putBoolean(CLAVE_REAL, real).remove(CLAVE_MOTIVO)
        if (pendiente(context) == real) editor.remove(CLAVE_PENDIENTE)
        editor.apply()
    }

    /** Por que no se ha podido leer config.yaml, para poder decirlo. */
    fun apuntarFallo(context: Context, motivo: String?) {
        prefs(context).edit()
            .putString(CLAVE_MOTIVO, motivo ?: "no he podido leer config.yaml")
            .apply()
    }

    fun motivo(context: Context): String? =
        prefs(context).getString(CLAVE_MOTIVO, null)

    /** Lo pedido desde el movil y todavia no aplicado, o null. */
    fun pendiente(context: Context): Boolean? {
        val bruto = prefs(context).getString(CLAVE_PENDIENTE, "") ?: ""
        if (bruto.isBlank()) return null
        val fila = runCatching { JSONObject(bruto) }.getOrNull() ?: return null
        if (System.currentTimeMillis() - fila.optLong("cuando") > CADUCIDAD_MS) return null
        return fila.optBoolean("pausar")
    }

    /**
     * Lo que hay que ensenar: lo pedido si esta en camino, si no lo real.
     *
     * null cuando todavia no se ha podido leer config.yaml. Es un estado de
     * verdad y no un "activos" por defecto: dandolo por activos, el
     * interruptor solo ofrecia pausar y no habia forma de reanudarlos.
     */
    fun pausados(context: Context): Boolean? {
        pendiente(context)?.let { return it }
        val guardados = prefs(context)
        if (!guardados.contains(CLAVE_REAL)) return null
        return guardados.getBoolean(CLAVE_REAL, false)
    }

    /** El cuerpo de la issue. La etiqueta es el contrato con aplicar_avisos.py. */
    fun cuerpo(pausar: Boolean): String =
        "### Avisos\n\n" + (if (pausar) "Pausar" else "Reanudar") + "\n"

    suspend fun enviar(context: Context, pausar: Boolean): Result<Unit> =
        withContext(Dispatchers.IO) {
            val token = Repositorio.token(context)
            if (token.isBlank()) {
                return@withContext Result.failure(
                    IllegalStateException(
                        "Falta el token de GitHub. Abre los ajustes y pega uno con " +
                            "permiso de Issues: Read and write."
                    )
                )
            }
            val peticion = JSONObject()
                .put("title", if (pausar) "Avisos: pausar" else "Avisos: reanudar")
                .put("body", cuerpo(pausar))

            runCatching {
                Topes.abrirIssue(Repositorio.repo(context), token, peticion.toString())
                prefs(context).edit()
                    .putString(
                        CLAVE_PENDIENTE,
                        JSONObject()
                            .put("pausar", pausar)
                            .put("cuando", System.currentTimeMillis())
                            .toString(),
                    )
                    .apply()
            }
        }
}
