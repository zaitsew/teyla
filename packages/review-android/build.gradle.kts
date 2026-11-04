// The toolchain a product with a current Compose stack already has. The library modules name no version of their own:
// they take these plugins from the root build, as a product's modules do.
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("com.android.library") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
}
