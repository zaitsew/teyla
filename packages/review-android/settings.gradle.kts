pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

// This build exists to test and to prove the package. A product does not use it: it links the two
// library folders into its own build (see README.md, "Quick start").
rootProject.name = "teyla-review-android"
include(":teyla-review")
include(":teyla-review-noop")
include(":fixture")
