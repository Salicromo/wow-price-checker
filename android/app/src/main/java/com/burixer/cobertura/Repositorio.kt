package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * De donde salen los datos.
 *
 * La app arranca con la foto que lleva dentro, para servir de algo antes de
 * configurar nada. Con un token de GitHub se baja el volcado de verdad del repo
 * privado y lo guarda en disco, asi que a partir de ahi tambien funciona sin
 * cobertura.
 *
 * Son dos repositorios: el del codigo, que es publico y donde se abren las
 * issues de topes y objetos, y el privado, `<ese>-privado`, con las subastas,
 * los personajes y los datos. El token tiene que poder leer los dos.
 */
object Repositorio {

    private const val PREFS = "cobertura"
    private const val CLAVE_TOKEN = "token"
    private const val CLAVE_REPO = "repo"
    private const val CLAVE_DESCARGA = "descargado_en"
    private const val FICHERO = "datos.json"
    private const val CATALOGO = "catalogo.json"
    private const val PRECIOS = "precios.json"
    private const val MERCADO = "mercado.json.gz"
    private const val HISTORIAL = "historial.json"

    // El catalogo y los precios los publica el workflow en su propia rama, para
    // no ensuciar el historial de main con un commit por hora.
    private const val RAMA_DATOS = "datos"

    // Y el volcado de cada maquina en otra, por lo mismo: sync_subastas.py
    // publica cada vez que sales al selector de personajes, y en main eso
    // eran veinte commits por tarde de juego.
    private const val RAMA_SUBASTAS = "subastas"

    const val REPO_POR_DEFECTO = "Salicromo/wow-price-checker"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun token(context: Context): String = prefs(context).getString(CLAVE_TOKEN, "").orEmpty()

    fun repo(context: Context): String =
        prefs(context).getString(CLAVE_REPO, REPO_POR_DEFECTO).orEmpty().ifBlank { REPO_POR_DEFECTO }

    /** El repositorio de las subastas y los datos, que no pueden ser publicos. */
    fun repoPrivado(context: Context): String = repo(context) + "-privado"

    fun descargadoEn(context: Context): Long = prefs(context).getLong(CLAVE_DESCARGA, 0L)

    fun guardarAjustes(context: Context, token: String, repo: String) {
        prefs(context).edit()
            .putString(CLAVE_TOKEN, token.trim())
            .putString(CLAVE_REPO, repo.trim().ifBlank { REPO_POR_DEFECTO })
            .apply()
    }

    /** El catalogo descargado; si no hay ninguno todavia, el que trae la app. */
    fun catalogo(context: Context): Catalogo = Parser.catalogo(
        leerCache(context, CATALOGO)
            ?: context.assets.open("catalogo.json").bufferedReader().use { it.readText() }
    )

    /** Los precios de los reinos. Sin descarga todavia no hay ninguno. */
    fun precios(context: Context): Precios =
        leerCache(context, PRECIOS)?.let { runCatching { parsearPrecios(it) }.getOrNull() }
            ?: Precios.VACIOS

    /** El buscador. Null si todavia no se ha descargado o no se puede leer. */
    fun mercado(context: Context): Mercado? = Mercado.leer(File(context.filesDir, MERCADO))

    /** Los ultimos 30 dias de tus objetos. Vacio hasta la primera descarga. */
    fun historial(context: Context): Historial =
        leerCache(context, HISTORIAL)?.let { runCatching { Historial.parsear(it) }.getOrNull() }
            ?: Historial.VACIO

    private fun leerCache(context: Context, nombre: String): String? {
        val fichero = File(context.filesDir, nombre)
        if (!fichero.isFile) return null
        return runCatching { fichero.readText() }.getOrNull()
    }

    /** Lo ultimo descargado; si no hay nada todavia, la foto de la app. */
    fun datos(context: Context): Datos {
        val cache = File(context.filesDir, FICHERO)
        val texto = if (cache.isFile) {
            runCatching { cache.readText() }.getOrNull()
        } else {
            null
        } ?: context.assets.open("snapshot.json").bufferedReader().use { it.readText() }
        return Parser.datos(texto)
    }

    fun hayDescarga(context: Context): Boolean = File(context.filesDir, FICHERO).isFile

    /**
     * Baja el volcado del repo privado y lo deja guardado.
     *
     * Se leen las dos carpetas enteras porque cada maquina tuya escribe su
     * propio fichero: quedarse con uno solo perderia los personajes de la otra.
     */
    /** Lo que trae una descarga: tus subastas y lo que se ha vendido desde la anterior. */
    data class Actualizacion(val datos: Datos, val vendidas: List<Subasta>)

    suspend fun actualizar(context: Context): Result<Actualizacion> = withContext(Dispatchers.IO) {
        val token = token(context)
        if (token.isBlank()) {
            return@withContext Result.failure(
                IllegalStateException(
                    "Falta el token de GitHub. Abre los ajustes y pega uno de solo " +
                        "lectura para el repositorio."
                )
            )
        }
        // El del codigo se resuelve antes de que `repo` pase a ser el privado:
        // a partir de esa linea el nombre queda tapado.
        val repoCodigo = repo(context)
        val repo = repoPrivado(context)

        runCatching {
            val subastas = JSONArray()
            var exportado = 0L
            for (nombre in listar(repo, "mis_subastas", token, RAMA_SUBASTAS)) {
                val fichero =
                    JSONObject(leer(repo, "mis_subastas/$nombre", token, RAMA_SUBASTAS))
                val array = fichero.optJSONArray("auctions") ?: JSONArray()
                for (i in 0 until array.length()) {
                    val subasta = array.getJSONObject(i)
                    exportado = maxOf(exportado, subasta.optLong("exportedAt", 0L))
                    subastas.put(subasta)
                }
            }

            val personajes = JSONArray()
            for (nombre in listar(repo, "mis_personajes", token, RAMA_SUBASTAS)) {
                val fichero =
                    JSONObject(leer(repo, "mis_personajes/$nombre", token, RAMA_SUBASTAS))
                val array = fichero.optJSONArray("characters") ?: JSONArray()
                for (i in 0 until array.length()) personajes.put(array.getJSONObject(i))
            }

            val fusion = JSONObject()
                .put("version", 1)
                .put("exportado", exportado)
                .put("auctions", subastas)
                .put("characters", personajes)

            // Lo vendido sale de comparar con la descarga anterior, asi que se
            // mira antes de pisarla. Con la foto que trae la app no se compara:
            // es de hace semanas y todo pareceria desaparecido.
            val cache = File(context.filesDir, FICHERO)
            val antes = if (cache.isFile) {
                runCatching { Parser.datos(cache.readText()).subastas }.getOrDefault(emptyList())
            } else {
                emptyList()
            }
            val nuevos = Parser.datos(fusion.toString())

            cache.writeText(fusion.toString())

            // Opcional, como el catalogo: sin ventas no se sabe que se vendio,
            // pero las subastas siguen sirviendo. Y sin ellas no se toca el
            // estado, o la siguiente vez todas las ventas parecerian nuevas.
            val vendidas = runCatching {
                val ficheros = listar(repo, "mis_ventas", token, RAMA_SUBASTAS)
                    .map { leer(repo, "mis_ventas/$it", token, RAMA_SUBASTAS) }
                val (estado, vendidas) = Ventas.avanzar(
                    Ventas.estado(context), antes, nuevos.subastas,
                    Ventas.leer(ficheros), System.currentTimeMillis(),
                )
                Ventas.guardar(context, estado)
                vendidas
            }.getOrDefault(emptyList())

            // El catalogo y los precios viven en otra rama y son opcionales: si
            // el workflow no los ha publicado todavia, las subastas que acabamos
            // de bajar siguen sirviendo.
            for (nombre in listOf(CATALOGO, PRECIOS, HISTORIAL)) {
                runCatching { leer(repo, nombre, token, RAMA_DATOS) }
                    .onSuccess { File(context.filesDir, nombre).writeText(it) }
            }
            // Comprimido, asi que se guarda tal cual llega. Tambien opcional.
            runCatching { leerBytes(repo, MERCADO, token, RAMA_DATOS) }
                .onSuccess { File(context.filesDir, MERCADO).writeBytes(it) }

            // Si los avisos estan pausados lo dice config.yaml, en main. Se lee
            // de ahi y no del catalogo porque el catalogo tarda hasta una hora
            // en regenerarse, y el interruptor tiene que confirmarse en cuanto
            // el workflow lo aplica.
            //
            // Del repositorio PUBLICO, no de `repo`, que aqui arriba es el
            // privado: config.yaml es codigo y vive con el codigo. Leerlo del
            // privado daba 404, y como el fallo se tragaba, la app se quedaba
            // creyendo para siempre que los avisos estaban activos y solo
            // ofrecia pausarlos.
            runCatching { leer(repoCodigo, "config.yaml", token) }
                .onSuccess { Avisos.apuntarConfig(context, it) }
                // No se deja morir: sin estado, el interruptor no sabe que
                // ofrecer, y hay que poder decirlo en pantalla.
                .onFailure { Avisos.apuntarFallo(context, it.message) }

            // Un tope que enviaste y que el catalogo recien bajado ya trae deja
            // de estar pendiente. Va aqui y no en la pantalla porque el catalogo
            // solo cambia cuando se descarga.
            runCatching { Topes.limpiarConfirmados(context, catalogo(context)) }

            prefs(context).edit().putLong(CLAVE_DESCARGA, System.currentTimeMillis()).apply()
            Actualizacion(nuevos, vendidas)
        }
    }

    private fun listar(
        repo: String,
        carpeta: String,
        token: String,
        rama: String? = null,
    ): List<String> {
        val cuerpo = String(
            peticion(
                "https://api.github.com/repos/$repo/contents/$carpeta" +
                    if (rama != null) "?ref=$rama" else "",
                token,
                "application/vnd.github+json",
            ),
            Charsets.UTF_8,
        )
        val array = JSONArray(cuerpo)
        return (0 until array.length())
            .map { array.getJSONObject(it) }
            .filter { it.optString("type") == "file" && it.optString("name").endsWith(".json") }
            .map { it.getString("name") }
    }

    private fun leer(
        repo: String,
        ruta: String,
        token: String,
        rama: String? = null,
    ): String = String(leerBytes(repo, ruta, token, rama), Charsets.UTF_8)

    private fun leerBytes(
        repo: String,
        ruta: String,
        token: String,
        rama: String? = null,
    ): ByteArray = peticion(
        "https://api.github.com/repos/$repo/contents/$ruta" +
            if (rama != null) "?ref=$rama" else "",
        token,
        // Con este Accept, GitHub devuelve el fichero tal cual en vez de un
        // JSON con el contenido en base64.
        "application/vnd.github.raw",
    )

    private fun peticion(url: String, token: String, accept: String): ByteArray {
        val conexion = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", accept)
            setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            setRequestProperty("User-Agent", "cobertura-app")
            connectTimeout = 15_000
            readTimeout = 30_000
        }
        try {
            val codigo = conexion.responseCode
            if (codigo == 401 || codigo == 403) {
                throw IllegalStateException(
                    "GitHub rechaza el token ($codigo). Comprueba que no ha caducado y " +
                        "que da permiso de lectura de contenido sobre ese repositorio."
                )
            }
            if (codigo == 404) {
                throw IllegalStateException(
                    // Con un repositorio privado, GitHub responde 404 y no 403
                    // cuando el token no llega a el: no delata que existe.
                    "GitHub no encuentra $url. Revisa el usuario y el nombre del " +
                        "repositorio en los ajustes, y que el token tenga acceso " +
                        "a ese repositorio (si es privado, GitHub da 404 en vez de 403)."
                )
            }
            if (codigo !in 200..299) {
                throw IllegalStateException("GitHub ha respondido $codigo.")
            }
            return conexion.inputStream.use { it.readBytes() }
        } finally {
            conexion.disconnect()
        }
    }
}
