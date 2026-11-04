// A tiny app that links the real module in `debug` and `internal` and the no-op in `release`, with R8 on in
// the two that are not debuggable. tests/test_review_android.py builds it and runs `teyla review store-check`.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "teyla.review.fixture"
    compileSdk = 36

    defaultConfig {
        applicationId = "teyla.review.fixture" // the same in every variant: no applicationIdSuffix
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    buildTypes {
        debug {
            isMinifyEnabled = false
            reviewChannel()
        }
        create("internal") {
            initWith(getByName("release"))
            reviewChannel()
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += "release"
        }
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug") // a fixture: never published
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    // `src/review` holds the product's review setup, with the channel key from BuildConfig, and only the two
    // build types that link the real module compile it. `src/release` holds a setup that does nothing.
    sourceSets {
        getByName("debug").java.srcDir("src/review/kotlin")
        getByName("internal").java.srcDir("src/review/kotlin")
    }
}

/** The channel address and the write-only key exist as BuildConfig fields only where they are defined: here, never in `release`. */
fun com.android.build.api.dsl.BuildType.reviewChannel() {
    buildConfigField("String", "TEYLA_REVIEW_URL", "\"http://localhost:8099\"")
    buildConfigField("String", "TEYLA_REVIEW_KEY", "\"fixture-write-only-key-0123456789\"")
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")

    debugImplementation(project(":teyla-review"))
    "internalImplementation"(project(":teyla-review"))
    releaseImplementation(project(":teyla-review-noop"))
}
