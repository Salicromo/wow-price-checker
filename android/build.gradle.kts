// Versiones fijadas a las que ya estan en la cache de Gradle de esta maquina,
// para que compilar no dependa de descargarse medio Maven.
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
}
