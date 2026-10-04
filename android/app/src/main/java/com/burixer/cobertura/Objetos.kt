package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * Anadir un objeto vigilado desde la app.
 *
 * Como los topes: la app NO escribe config.yaml, abre una issue y un workflow
 * la aplica. El token sigue sin permiso de escritura sobre el contenido.
 *
 * Aqui no hay "pendientes", al reves que en Topes: un tope pendiente existe
 * porque la app ensena el numero viejo al lado, pero un objeto que aun no esta
 * simplemente no sale en la lista, y se vera en la pasada siguiente.
 */
object Objetos {

    /** Las dos opciones del desplegable 'Tipo', tal cual las lee el parser. */
    const val EQUIPO = "Equipo (tabla por ilvl)"
    const val PATRON = "Patron o receta (precio unico)"

    /** Lo que escribe GitHub cuando dejas en blanco un campo opcional. */
    private const val SIN_RESPUESTA = "_No response_"

    /** Ningun ilvl real llega tan alto. Espeja _ILVL_MAXIMO en anadir_objeto.py. */
    const val ILVL_MAXIMO = 2000

    /**
     * Quita los saltos de linea del texto escrito a mano.
     *
     * Si el usuario pega un enlace con un salto de linea de mas (o varias
     * lineas), un salto suelto ahi partiria el bloque `### Objeto` en dos y el
     * parser del otro lado leeria solo la primera linea.
     */
    private fun normalizado(objeto: String): String =
        objeto.replace(Regex("\\s+"), " ").trim()

    /**
     * El cuerpo de la issue.
     *
     * Tiene que salir identico al que genera el formulario de GitHub, que titula
     * cada bloque con la ETIQUETA del campo. Si cambias una etiqueta aqui,
     * cambiala tambien en .github/ISSUE_TEMPLATE/objeto.yml y en
     * anadir_objeto.py.
     */
    fun cuerpo(objeto: String, tipo: String, topesIlvl: List<Pair<Int, Long>>?, tope: Long?): String =
        buildString {
            append("### Objeto\n\n").append(normalizado(objeto)).append("\n\n")
            append("### Tipo\n\n").append(tipo).append("\n\n")
            append("### Topes por ilvl\n\n")
            if (topesIlvl.isNullOrEmpty()) {
                append(SIN_RESPUESTA)
            } else {
                // Uno por linea: la coma tambien es separador de miles, y el
                // parser del otro lado lee un escalon por linea.
                append(topesIlvl.sortedBy { it.first }.joinToString("\n") { "${it.first}: ${it.second}" })
            }
            append("\n\n")
            append("### Tope, en oro\n\n")
                .append(tope?.toString() ?: SIN_RESPUESTA).append("\n")
        }

    /**
     * Abre la issue que anade el objeto.
     *
     * Al reves que un tope, esto NO es idempotente: si se repite, el workflow
     * contesta que ese objeto ya esta vigilado, que es la respuesta correcta.
     */
    suspend fun enviar(
        context: Context,
        objeto: String,
        tipo: String,
        topesIlvl: List<Pair<Int, Long>>?,
        tope: Long?,
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
        if (objeto.isBlank()) {
            return@withContext Result.failure(
                IllegalArgumentException("Escribe el enlace de Wowhead o el nombre.")
            )
        }
        if (tipo == PATRON && (tope == null || tope <= 0)) {
            return@withContext Result.failure(
                IllegalArgumentException("Un patron necesita un precio mayor que cero.")
            )
        }
        if (tipo == EQUIPO) {
            val topes = topesIlvl.orEmpty()
            val ilvls = topes.map { it.first }
            if (topes.isEmpty() ||
                topes.any { it.first <= 0 || it.first > ILVL_MAXIMO || it.second <= 0 } ||
                ilvls.toSet().size != ilvls.size
            ) {
                return@withContext Result.failure(
                    IllegalArgumentException(
                        "Pon al menos un ilvl con su tope, sin repetir ilvl y con " +
                            "numeros mayores que cero."
                    )
                )
            }
        }

        val peticion = JSONObject()
            .put("title", "Objeto: ${normalizado(objeto)}")
            .put("body", cuerpo(objeto, tipo, topesIlvl, tope))
            .put("labels", JSONArray().put("objeto"))

        runCatching { Topes.abrirIssue(Repositorio.repo(context), token, peticion.toString()) }
    }
}
