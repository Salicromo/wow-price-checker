package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Cambiar un tope desde la app.
 *
 * La app NO escribe config.yaml: abre una issue y un workflow la aplica. Eso es
 * lo que permite que el token siga sin permiso de escritura sobre el contenido
 * --le basta `Issues: Read and write`--, y que la edicion del YAML, que es la
 * parte delicada, la haga Python con sus tests en vez de Kotlin a ciegas.
 *
 * El cuerpo que se manda es exactamente el que genera un formulario de GitHub,
 * porque al otro lado hay un solo parser para los tres caminos.
 */
object Topes {

    private const val PREFS = "cobertura"
    private const val CLAVE_PENDIENTES = "topes_pendientes"

    /** La opcion del desplegable para lo que no escala. */
    const val SIN_ILVL = "sin ilvl (precio unico)"

    /**
     * Cuanto se cree un pendiente antes de rendirse.
     *
     * El tope nuevo tarda como mucho una hora en verse, que es lo que tarda la
     * pasada en regenerar el catalogo. Seis horas es muy por encima: si a esas
     * alturas sigue pendiente es que algo salio mal, y ahi vale mas volver a
     * ensenar la verdad de config.yaml que un pendiente eterno.
     */
    private const val CADUCIDAD_MS = 6 * 60 * 60 * 1000L

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** La clave de un tope: el objeto y su escalon. `ilvl` a null si no escala. */
    fun clave(itemId: Int, ilvl: Int?): String = "$itemId/${ilvl ?: "plano"}"

    /**
     * Los topes enviados y todavia no confirmados, por (objeto, ilvl).
     *
     * Van a disco y no a memoria porque la app se muere al salir: en memoria el
     * pendiente moriria con ella y volverias a ver el numero viejo sin ninguna
     * explicacion, justo despues de haberlo cambiado.
     */
    fun pendientes(context: Context): Map<String, Long> {
        val bruto = prefs(context).getString(CLAVE_PENDIENTES, "") ?: ""
        if (bruto.isBlank()) return emptyMap()

        val raiz = runCatching { JSONObject(bruto) }.getOrNull() ?: return emptyMap()
        val ahora = System.currentTimeMillis()
        val vivos = HashMap<String, Long>()
        for (clave in raiz.keys()) {
            val fila = raiz.optJSONObject(clave) ?: continue
            if (ahora - fila.optLong("cuando") > CADUCIDAD_MS) continue
            vivos[clave] = fila.optLong("tope")
        }
        return vivos
    }

    fun pendiente(context: Context, itemId: Int, ilvl: Int?): Long? =
        pendientes(context)[clave(itemId, ilvl)]

    private fun guardarPendiente(context: Context, itemId: Int, ilvl: Int?, tope: Long) {
        val raiz = runCatching {
            JSONObject(prefs(context).getString(CLAVE_PENDIENTES, "") ?: "")
        }.getOrElse { JSONObject() }

        raiz.put(
            clave(itemId, ilvl),
            JSONObject()
                .put("tope", tope)
                .put("cuando", System.currentTimeMillis()),
        )
        prefs(context).edit().putString(CLAVE_PENDIENTES, raiz.toString()).apply()
    }

    /**
     * Olvida los pendientes que el catalogo descargado ya confirma.
     *
     * Se llama despues de cada descarga: en cuanto el tope que bajamos coincide
     * con el que enviaste, el aviso de "pendiente" sobra.
     */
    fun limpiarConfirmados(context: Context, catalogo: Catalogo) {
        val vivos = pendientes(context)
        if (vivos.isEmpty()) return

        val reales = HashMap<String, Long>()
        for (objeto in catalogo.objetos) {
            objeto.tope?.let { reales[clave(objeto.id, null)] = it }
            for (escalon in objeto.escalones) {
                reales[clave(objeto.id, escalon.ilvl)] = escalon.tope
            }
        }

        val raiz = JSONObject()
        val bruto = runCatching {
            JSONObject(prefs(context).getString(CLAVE_PENDIENTES, "") ?: "")
        }.getOrElse { JSONObject() }

        for ((clave, tope) in vivos) {
            if (reales[clave] == tope) continue
            bruto.optJSONObject(clave)?.let { raiz.put(clave, it) }
        }
        prefs(context).edit().putString(CLAVE_PENDIENTES, raiz.toString()).apply()
    }

    /**
     * El cuerpo de la issue.
     *
     * Tiene que salir identico al que genera un formulario de GitHub, que titula
     * cada bloque con la ETIQUETA del campo. Si cambias una etiqueta aqui,
     * cambiala tambien en .github/ISSUE_TEMPLATE y en aplicar_tope.py.
     */
    fun cuerpo(objetoEn: String, ilvl: Int?, tope: Long): String = buildString {
        append("### Objeto\n\n").append(objetoEn).append("\n\n")
        append("### ilvl\n\n").append(ilvl?.toString() ?: SIN_ILVL).append("\n\n")
        append("### Tope nuevo, en oro\n\n").append(tope).append("\n")
    }

    /**
     * Abre la issue que cambia el tope.
     *
     * La operacion es idempotente --"pon este tope a este valor" aplicado dos
     * veces da lo mismo--, asi que si la app muere entre el envio y la respuesta
     * no pasa nada por repetirlo.
     */
    suspend fun enviar(
        context: Context,
        objeto: Objeto,
        ilvl: Int?,
        tope: Long,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        val token = Repositorio.token(context)
        if (token.isBlank()) {
            return@withContext Result.failure(
                IllegalStateException(
                    "Falta el token de GitHub. Abre los ajustes y pega uno con " +
                        "permiso de Issues: Read and write."
                )
            )
        }
        if (tope <= 0) {
            return@withContext Result.failure(
                IllegalArgumentException("El tope tiene que ser mayor que cero.")
            )
        }

        val donde = if (ilvl != null) " ilvl $ilvl" else ""
        val peticion = JSONObject()
            .put("title", "Tope: ${objeto.en}$donde")
            .put("body", cuerpo(objeto.en, ilvl, tope))
            .put("labels", org.json.JSONArray().put("tope"))

        runCatching {
            abrirIssue(Repositorio.repo(context), token, peticion.toString())
            guardarPendiente(context, objeto.id, ilvl, tope)
        }
    }

    /** Un tope apuntado en la cesta, todavia sin enviar. */
    data class Cambio(val objeto: Objeto, val ilvl: Int?, val tope: Long)

    /**
     * El cuerpo de la issue de la cesta: un bloque "Cambios" con una linea
     * "Objeto | ilvl | tope" por tope. aplicar_tope.py los aplica todos o
     * ninguno, en un solo commit.
     */
    fun cuerpoVarios(cambios: List<Cambio>): String = buildString {
        append("### Cambios\n\n")
        for (c in cambios) {
            append(c.objeto.en).append(" | ")
                .append(c.ilvl?.toString() ?: SIN_ILVL).append(" | ")
                .append(c.tope).append("\n")
        }
    }

    /** Envia toda la cesta en una sola issue. */
    suspend fun enviarVarios(
        context: Context,
        cambios: List<Cambio>,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        val token = Repositorio.token(context)
        if (token.isBlank()) {
            return@withContext Result.failure(
                IllegalStateException(
                    "Falta el token de GitHub. Abre los ajustes y pega uno con " +
                        "permiso de Issues: Read and write."
                )
            )
        }
        if (cambios.isEmpty() || cambios.any { it.tope <= 0 }) {
            return@withContext Result.failure(
                IllegalArgumentException("El tope tiene que ser mayor que cero.")
            )
        }

        // El workflow reconoce la issue por el prefijo "Tope:" del titulo.
        val peticion = JSONObject()
            .put("title", "Tope: ${cambios.size} cambios")
            .put("body", cuerpoVarios(cambios))
            .put("labels", org.json.JSONArray().put("tope"))

        runCatching {
            abrirIssue(Repositorio.repo(context), token, peticion.toString())
            cambios.forEach { guardarPendiente(context, it.objeto.id, it.ilvl, it.tope) }
        }
    }

    internal fun abrirIssue(repo: String, token: String, cuerpo: String) {
        val conexion = (URL("https://api.github.com/repos/$repo/issues").openConnection()
            as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            setRequestProperty("User-Agent", "cobertura-app")
            connectTimeout = 15_000
            readTimeout = 30_000
        }
        try {
            conexion.outputStream.use { it.write(cuerpo.toByteArray()) }
            when (val codigo = conexion.responseCode) {
                in 200..299 -> Unit
                401, 403 -> throw IllegalStateException(
                    "GitHub rechaza el token ($codigo). Para cambiar topes o añadir " +
                        "objetos necesita permiso de Issues: Read and write, que es " +
                        "distinto del de lectura que basta para ver los datos."
                )
                404 -> throw IllegalStateException(
                    "GitHub no encuentra el repositorio $repo, o el token no llega a el."
                )
                410 -> throw IllegalStateException(
                    "Las issues estan desactivadas en $repo. Actívalas en los ajustes " +
                        "del repositorio."
                )
                else -> throw IllegalStateException("GitHub ha respondido $codigo.")
            }
        } finally {
            conexion.disconnect()
        }
    }
}
