plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "teyla.review"
    compileSdk = 36

    defaultConfig {
        minSdk = 26
        // The rules a product's R8 run must apply: they keep the marker class that `teyla review store-check` looks for.
        consumerProguardFiles("consumer-rules.pro")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    // The tests are plain JVM tests: no Android class is called in them.
    testOptions { unitTests.isReturnDefaultValues = false }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")

    testImplementation("junit:junit:4.13.2")
}

tasks.withType<Test>().configureEach {
    // Where the golden capture lives in the Teyla repo. Absent in a vendored copy, which has no tests.
    systemProperty("teyla.fixtures", rootDir.resolve("../../tests/fixtures").absolutePath)
    // `-Pteyla.golden.update=1` rewrites tests/fixtures/review-android-capture.json from the encoder.
    if (project.hasProperty("teyla.golden.update")) systemProperty("teyla.golden.update", "1")
}
