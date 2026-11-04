package teyla.review

import android.app.Activity
import android.app.Application
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.ConnectivityManager
import android.net.Network
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.PixelCopy
import android.widget.Toast
import java.io.ByteArrayOutputStream
import java.io.File
import java.lang.ref.WeakReference
import java.time.Instant
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** What one opening of review mode froze: the masked picture and everything the form needs. */
internal class Session(
    val frozen: Frozen,
    val bitmap: Bitmap,
    val png: ByteArray,
    val windowWidthDp: Double,
    val windowHeightDp: Double,
    /** A map, video or 3D area can come out blank in a window copy; the form says so when the picture is. */
    val blank: Boolean,
    val television: Boolean,
    val requiresHealthConsent: Boolean,
)

/**
 * Review mode: freezes the window, hands the picture to [ReviewActivity] and sends what the tester wrote.
 * This class is the marker of the real module. Its name, `teyla/review/ReviewOverlay`, is what
 * `teyla review store-check` looks for in the dex files of a production artifact; the consumer ProGuard
 * rules keep it under R8, and the no-op module has no class of this name.
 */
internal object ReviewOverlay {
    private const val TAG = "TeylaReview"

    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "teyla-review").apply { isDaemon = true } }
    private val opening = AtomicBoolean(false)

    private var app: Application? = null
    private var config: ReviewConfig? = null
    private var queue: FileQueue? = null
    private var kv: KeyValue? = null
    private var current: WeakReference<Activity>? = null
    private var sensors: SensorManager? = null
    private var shake: Boolean = false
    private val detector = ShakeDetector()

    @Volatile var session: Session? = null
        private set

    fun install(application: Application, cfg: ReviewConfig) {
        val route = routeFor(cfg) ?: return
        app = application
        config = cfg
        ReviewState.strings = cfg.strings
        val prefs = application.getSharedPreferences("teyla_review", Context.MODE_PRIVATE)
        kv = object : KeyValue {
            override fun getBoolean(key: String) = prefs.getBoolean(key, false)
            override fun putBoolean(key: String, value: Boolean) { prefs.edit().putBoolean(key, value).apply() }
        }
        // Nothing goes out before the tester has accepted the first-send notice, whatever waits in the queue.
        queue = FileQueue(File(application.filesDir, "teyla-review/queue"), { e ->
            if (isAccepted(kv)) deliverWith(route, e) else ChannelResult.Retry
        })

        val points = entryPoints(Environment.uiModeType(application), hasAccelerometer(application), cfg.shake)
        shake = points.shake
        sensors = application.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
        application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityResumed(activity: Activity) {
                if (activity is ReviewActivity) return
                current = WeakReference(activity)
                startShake()
            }

            override fun onActivityPaused(activity: Activity) {
                if (activity is ReviewActivity) return
                stopShake()
            }

            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) {}
            override fun onActivityStarted(activity: Activity) {}
            override fun onActivityStopped(activity: Activity) {}
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) {}
            override fun onActivityDestroyed(activity: Activity) {}
        })
        watchNetwork(application)
        flush()
    }

    private fun hasAccelerometer(context: Context): Boolean =
        (context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager)?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) != null

    private val shakeListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            if (event.values.size < 3) return
            if (detector.onSample(event.values[0], event.values[1], event.values[2], SystemClock.elapsedRealtime())) {
                current?.get()?.let { present(it) }
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    private fun startShake() {
        if (!shake) return
        val sm = sensors ?: return
        sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sm.registerListener(shakeListener, it, SensorManager.SENSOR_DELAY_UI) }
    }

    private fun stopShake() { sensors?.unregisterListener(shakeListener) }

    /** Unsent captures go again when the network returns. Without the permission or the service the start-up and Send still flush. */
    private fun watchNetwork(application: Application) {
        try {
            val cm = application.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
            cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) { flush() }
            })
        } catch (e: RuntimeException) {
            Log.w(TAG, "network changes are not watched: " + e.javaClass.simpleName)
        }
    }

    fun flush() {
        val q = queue ?: return
        worker.execute { try { q.flush() } catch (e: Exception) { Log.w(TAG, "flush failed: " + e.javaClass.simpleName) } }
    }

    /** Freezes the window of [activity] and opens the form. Does nothing while a form is open or being prepared. */
    fun present(activity: Activity) {
        if (Looper.myLooper() != Looper.getMainLooper()) { main.post { present(activity) }; return }
        val cfg = config ?: return
        if (session != null || !opening.compareAndSet(false, true)) return
        val strings = cfg.strings
        fun fail(message: String) { opening.set(false); Toast.makeText(activity, message, Toast.LENGTH_LONG).show() }

        val window = activity.window
        // FLAG_SECURE: the window is protected on purpose, and a copy of it would be black. Refuse and say so;
        // never send a blank picture as if it were the screen.
        if (isSecure(window.attributes.flags)) { fail(strings.secureScreen); return }
        val decor = window.decorView
        val w = decor.width
        val h = decor.height
        if (w <= 0 || h <= 0) { fail(strings.pictureFailed); return }
        val density = activity.resources.displayMetrics.density.toDouble().coerceAtLeast(0.5)
        // Bounds are read now, on the main thread, as close to the copy as they can be.
        val snapshot = ReviewState.registry.snapshot(w / density, h / density, density)
        val bitmap = try { Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888) } catch (e: OutOfMemoryError) { fail(strings.pictureFailed); return }
        try {
            PixelCopy.request(window, bitmap, { result ->
                if (result != PixelCopy.SUCCESS) { bitmap.recycle(); fail(strings.pictureFailed); return@request }
                worker.execute { finishFreeze(activity, cfg, bitmap, snapshot, density) }
            }, main)
        } catch (e: IllegalArgumentException) {
            bitmap.recycle(); fail(strings.pictureFailed)
        }
    }

    private fun finishFreeze(activity: Activity, cfg: ReviewConfig, source: Bitmap, snapshot: Snapshot, density: Double) {
        try {
            val w = source.width
            val h = source.height
            val pixels = IntArray(w * h)
            source.getPixels(pixels, 0, w, 0, 0, w, h)
            val buffer = PixelBuffer(w, h, pixels)
            // Black first, then everything else: the form, the hash and the file all see the masked picture.
            blackOut(buffer, snapshot.privateFrames, density)
            val blank = isBlank(buffer)
            source.setPixels(pixels, 0, w, 0, 0, w, h)

            var bitmap = source
            var png = encodePng(bitmap)
            val factor = shrinkFactor(png.size, density)
            var pixelScale = density
            if (factor < 1.0) {
                bitmap = Bitmap.createScaledBitmap(source, (w * factor).toInt().coerceAtLeast(1), (h * factor).toInt().coerceAtLeast(1), true)
                png = encodePng(bitmap)
                pixelScale = density * factor
                source.recycle()
            }
            val windowW = w / density
            val windowH = h / density
            val uiMode = Environment.uiModeType(activity)
            val frozen = Frozen(
                id = newId(),
                app = Environment.app(activity, cfg),
                environment = Environment.environment(activity, windowW, windowH, density),
                currentScreen = ReviewState.currentScreen,
                anchors = snapshot.anchors,
                frames = snapshot.privateFrames,
                sha256 = sha256Hex(png),
                pixelWidth = bitmap.width,
                pixelHeight = bitmap.height,
                pixelScale = pixelScale,
            )
            val s = Session(frozen, bitmap, png, windowW, windowH, blank, isTelevision(uiMode), cfg.requiresHealthConsent)
            main.post {
                session = s
                opening.set(false)
                activity.startActivity(Intent(activity, ReviewActivity::class.java))
            }
        } catch (e: Exception) {
            Log.w(TAG, "freeze failed: " + e.javaClass.simpleName)
            main.post {
                opening.set(false)
                Toast.makeText(activity, cfg.strings.pictureFailed, Toast.LENGTH_LONG).show()
            }
        } catch (e: OutOfMemoryError) {
            main.post {
                opening.set(false)
                Toast.makeText(activity, cfg.strings.pictureFailed, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun encodePng(bitmap: Bitmap): ByteArray {
        val out = ByteArrayOutputStream(256 * 1024)
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        return out.toByteArray()
    }

    /** Whether the form needs the first-send notice before it sends. */
    fun noticeNeeded(): Boolean = isNeeded(true, kv)

    fun acceptNotice() { accept(kv) }

    /** Turns the tester's draft into the capture, saves it and tries once. The callback runs on the main thread. */
    fun send(draft: Draft, done: (SendOutcome) -> Unit) {
        val s = session
        val q = queue
        if (s == null || q == null) { done(SendOutcome.Unsaved); return }
        worker.execute {
            val outcome = try {
                val record = recordFor(s.frozen, draft, Instant.now())
                val entry = QueueEntry(s.frozen.id, System.currentTimeMillis(), encodeCapture(record), s.png)
                q.send(entry)
            } catch (e: Exception) {
                SendOutcome.Unsaved
            }
            main.post { done(outcome) }
            if (outcome == SendOutcome.Delivered) flush()
        }
    }

    fun closeSession() {
        session?.bitmap?.recycle()
        session = null
    }
}
