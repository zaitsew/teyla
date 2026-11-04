package teyla.review

/**
 * What a screen has registered with `reviewAnchor`, `reviewScreen` and `reviewPrivate`. An entry does not
 * hold bounds: it holds a function that reads them when the capture is taken, so a scrolled list reports
 * where its rows are now. Bounds are in px, from the top left of the window; [snapshot] turns them into dp.
 */
internal enum class Kind { Anchor, Screen, Private }

internal class Entry(
    val order: Long,
    val kind: Kind,
    val id: String,
    val role: ReviewRole,
    val strings: List<String>,
    /** The window bounds in px now, or null when the node is not on screen. */
    val bounds: () -> Frame?,
)

internal class Snapshot(val anchors: List<Anchor>, val privateFrames: List<Frame>)

internal class Registry {
    private val lock = Any()
    private val entries = LinkedHashMap<Long, Entry>()
    private var next = 0L

    fun add(kind: Kind, id: String, role: ReviewRole, strings: List<String>, bounds: () -> Frame?): Long = synchronized(lock) {
        val key = next++
        entries[key] = Entry(key, kind, id, role, strings, bounds)
        key
    }

    fun remove(key: Long) { synchronized(lock) { entries.remove(key) } }

    fun count(): Int = synchronized(lock) { entries.size }

    /**
     * Reads every entry now. Anchors keep registration order, at most 200, those with a box that touches the
     * window; each takes the screen of the smallest `reviewScreen` area that contains its centre. A private area
     * that is not on screen hides nothing. One whose box is not a finite number is kept as it is, and the
     * painter hides the whole picture for it.
     */
    fun snapshot(windowWidthDp: Double, windowHeightDp: Double, density: Double): Snapshot {
        val list = synchronized(lock) { entries.values.toList() }
        fun dp(f: Frame) = Frame(f.x / density, f.y / density, f.width / density, f.height / density)
        fun read(e: Entry): Frame? = try { e.bounds()?.let { dp(it) } } catch (t: Exception) { Frame(Double.NaN, 0.0, 0.0, 0.0) }

        val screens = list.filter { it.kind == Kind.Screen }.mapNotNull { e -> read(e)?.takeIf { it.isFinite }?.let { e.id to it } }
        val frames = ArrayList<Frame>()
        for (e in list.filter { it.kind == Kind.Private }) {
            val r = read(e) ?: continue
            if (!r.isFinite) { frames.add(r); continue }
            if (r.width == 0.0 && r.height == 0.0) continue
            val g = grown(r)
            if (intersectsWindow(g, windowWidthDp, windowHeightDp)) frames.add(g)
        }
        val anchors = ArrayList<Anchor>()
        for (e in list.filter { it.kind == Kind.Anchor }) {
            if (anchors.size >= MAX_ANCHORS) break
            val b = read(e) ?: continue
            if (!b.isFinite || b.width == 0.0 || b.height == 0.0 || !intersectsWindow(b, windowWidthDp, windowHeightDp)) continue
            val cx = b.x + b.width / 2
            val cy = b.y + b.height / 2
            val screen = screens.filter { inFrame(it.second, cx, cy) }.minByOrNull { it.second.area }?.first
            anchors.add(Anchor(e.id, e.role, Frame(round2(b.x), round2(b.y), round2(b.width), round2(b.height)), screen, e.strings))
        }
        return Snapshot(redactAnchors(anchors, frames), frames)
    }
}
