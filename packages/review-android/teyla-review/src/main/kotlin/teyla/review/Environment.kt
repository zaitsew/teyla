package teyla.review

import android.app.UiModeManager
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import java.util.Locale

/** Facts about the app and the device, read once per capture. The device name the owner gave is never read. */
internal object Environment {
    fun uiModeType(context: Context): Int =
        (context.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager)?.currentModeType ?: Configuration.UI_MODE_TYPE_NORMAL

    @Suppress("DEPRECATION")
    fun app(context: Context, config: ReviewConfig): AppFacts {
        val pm = context.packageManager
        val info = try { pm.getPackageInfo(context.packageName, 0) } catch (e: PackageManager.NameNotFoundException) { null }
        val debuggable = (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        val label = try { context.applicationInfo.loadLabel(pm).toString() } catch (e: Exception) { null }
        val build = if (info == null) "0" else if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toString() else info.versionCode.toString()
        return AppFacts(
            bundleId = context.packageName,
            name = config.name ?: label,
            version = config.version ?: info?.versionName ?: "0",
            build = config.build ?: build,
            commit = config.commit,
            product = config.product,
            configuration = config.configuration?.takeIf { it in CONFIGURATIONS } ?: if (debuggable) "debug" else "play_internal",
        )
    }

    fun environment(context: Context, widthDp: Double, heightDp: Double, density: Double): EnvironmentFacts {
        val res = context.resources.configuration
        val locale = if (Build.VERSION.SDK_INT >= 24) res.locales.get(0) else Locale.getDefault()
        val dark = (res.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        return EnvironmentFacts(
            os = "Android " + Build.VERSION.RELEASE,
            model = Build.MODEL ?: "unknown",
            locale = locale.toString().ifEmpty { "en" },
            language = locale.language.takeIf { it.length >= 2 },
            dark = dark,
            screen = ScreenFacts(widthDp, heightDp, density),
        )
    }
}
