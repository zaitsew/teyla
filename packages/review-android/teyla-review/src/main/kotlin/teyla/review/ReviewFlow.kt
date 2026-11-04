package teyla.review

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp

private enum class Step { Point, Comment, Done }

/**
 * Point at a spot or choose the whole screen, write, preview, accept the first-send notice, send, done.
 * A touch screen taps and drags; a D-pad moves a cross with the arrow keys and chooses with OK. Every
 * control is an ordinary focusable one, so a TV remote reaches all of them.
 */
@Composable
internal fun ReviewFlow(session: Session, strings: ReviewStrings, onClose: () -> Unit) {
    var step by rememberSaveable { mutableStateOf(Step.Point) }
    var tapX by rememberSaveable { mutableStateOf<Double?>(null) }
    var tapY by rememberSaveable { mutableStateOf<Double?>(null) }
    var region by remember { mutableStateOf<Frame?>(null) }
    var comment by rememberSaveable { mutableStateOf("") }
    var healthOk by rememberSaveable { mutableStateOf(false) }
    var sending by remember { mutableStateOf(false) }
    var saveFailed by remember { mutableStateOf(false) }
    var showNotice by remember { mutableStateOf(false) }
    var delivered by remember { mutableStateOf(false) }
    val tap = if (tapX != null && tapY != null) Point(tapX!!, tapY!!) else null

    fun doSend() {
        sending = true
        saveFailed = false
        ReviewOverlay.send(Draft(tap, region, comment)) { outcome ->
            sending = false
            when (outcome) {
                SendOutcome.Unsaved -> saveFailed = true
                else -> { delivered = outcome == SendOutcome.Delivered; step = Step.Done }
            }
        }
    }

    BackHandler(enabled = step != Step.Done) {
        if (step == Step.Comment && !sending) step = Step.Point else if (step == Step.Point) onClose()
    }

    BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding()) {
        val wide = maxWidth > maxHeight
        val panelWidth = maxWidth * 0.4f
        val picture: @Composable (Modifier) -> Unit = { m ->
            PointingPicture(session, step == Step.Point, tap, region, m) { t, r -> tapX = t?.x; tapY = t?.y; region = r }
        }
        val panel: @Composable (Modifier) -> Unit = { m ->
            Column(m.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                when (step) {
                    Step.Point -> PointPanel(session, strings, tap, region, onExit = onClose, onNext = { step = Step.Comment })
                    Step.Comment -> CommentPanel(
                        session, strings, comment, { comment = it }, healthOk, { healthOk = it }, sending, saveFailed,
                        onBack = { step = Step.Point },
                        onSend = { if (ReviewOverlay.noticeNeeded()) showNotice = true else doSend() },
                    )
                    Step.Done -> DonePanel(strings, delivered, onClose)
                }
            }
        }
        if (wide) {
            Row(Modifier.fillMaxSize()) {
                picture(Modifier.weight(1f).fillMaxSize().padding(16.dp))
                panel(Modifier.width(panelWidth).fillMaxSize())
            }
        } else {
            Column(Modifier.fillMaxSize()) {
                picture(Modifier.weight(if (step == Step.Point) 1f else 0.45f).fillMaxWidth().padding(16.dp))
                panel(Modifier.weight(if (step == Step.Point) 0.55f else 1f).fillMaxWidth())
            }
        }
    }

    if (showNotice) {
        AlertDialog(
            onDismissRequest = { showNotice = false },
            title = { Text(strings.noticeTitle) },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(strings.noticeCaptured)
                    Text(strings.noticeRecipient)
                    Text(strings.noticeWhy)
                    Text(strings.noticeRetention)
                }
            },
            confirmButton = { TextButton(onClick = { ReviewOverlay.acceptNotice(); showNotice = false; doSend() }) { Text(strings.noticeOK) } },
            dismissButton = { TextButton(onClick = { showNotice = false }) { Text(strings.noticeCancel) } },
        )
    }
}

@Composable
private fun PointPanel(
    session: Session, strings: ReviewStrings, tap: Point?, region: Frame?, onExit: () -> Unit, onNext: () -> Unit,
) {
    Text(strings.modeTitle, style = MaterialTheme.typography.titleLarge)
    Text(if (session.television) strings.dpadHint else strings.modeHint)
    if (region != null) Text(strings.areaChosen, color = MaterialTheme.colorScheme.primary)
    else if (tap != null) Text(strings.spotChosen, color = MaterialTheme.colorScheme.primary)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onExit) { Text(strings.exit) }
        Button(onClick = onNext, enabled = tap != null) { Text(strings.next) }
    }
    TextButton(onClick = onNext) { Text(strings.wholeScreen) }
}

@Composable
private fun CommentPanel(
    session: Session, strings: ReviewStrings,
    comment: String, onComment: (String) -> Unit, healthOk: Boolean, onHealth: (Boolean) -> Unit,
    sending: Boolean, failed: Boolean, onBack: () -> Unit, onSend: () -> Unit,
) {
    Text(strings.commentTitle, style = MaterialTheme.typography.titleLarge)
    OutlinedTextField(
        value = comment, onValueChange = onComment, enabled = !sending,
        placeholder = { Text(strings.placeholder) }, minLines = 3, modifier = Modifier.fillMaxWidth(),
    )
    Text(strings.previewCaption, style = MaterialTheme.typography.bodySmall)
    if (session.blank) Text(strings.blankNote, style = MaterialTheme.typography.bodySmall)
    if (session.requiresHealthConsent) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = healthOk, onCheckedChange = onHealth)
            Text(strings.healthConsent, style = MaterialTheme.typography.bodyMedium)
        }
    }
    if (failed) Text(strings.saveFailed, color = MaterialTheme.colorScheme.error)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onBack, enabled = !sending) { Text(strings.back) }
        Button(onClick = onSend, enabled = canSend(comment, sending, session.requiresHealthConsent, healthOk)) {
            Text(if (sending) strings.saving else if (failed) strings.retry else strings.send)
        }
    }
}

@Composable
private fun DonePanel(strings: ReviewStrings, delivered: Boolean, onClose: () -> Unit) {
    Text(if (delivered) strings.sentTitle else strings.savedTitle, style = MaterialTheme.typography.titleLarge)
    Text(if (delivered) strings.sentDetail else strings.savedDetail)
    Spacer(Modifier.height(4.dp))
    Button(onClick = onClose) { Text(strings.done) }
}

/**
 * The frozen picture, fitted into its box. Tap for a spot, drag for an area; with a D-pad the arrow keys move
 * a cross and OK chooses it. An arrow key at the edge is not used, so focus can leave for the buttons.
 */
@Composable
private fun PointingPicture(
    session: Session, interactive: Boolean, tap: Point?, region: Frame?, modifier: Modifier,
    onPoint: (Point?, Frame?) -> Unit,
) {
    val image = remember(session) { session.bitmap.asImageBitmap() }
    val aspect = session.bitmap.width.toDouble() / session.bitmap.height
    var box by remember { mutableStateOf(IntSize.Zero) }
    var cursor by remember { mutableStateOf(Point(session.windowWidthDp / 2, session.windowHeightDp / 2)) }
    var focused by remember { mutableStateOf(false) }
    var dragFrom by remember { mutableStateOf<Point?>(null) }
    val focus = remember { FocusRequester() }
    val density = androidx.compose.ui.platform.LocalDensity.current.density
    val primary = MaterialTheme.colorScheme.primary
    LaunchedEffect(session.television, interactive) { if (session.television && interactive) runCatching { focus.requestFocus() } }

    fun fit() = fitInside(box.width.toDouble(), box.height.toDouble(), aspect)
    fun at(o: Offset) = toWindow(fit(), o.x.toDouble(), o.y.toDouble(), session.windowWidthDp, session.windowHeightDp)

    val keys = Modifier.onKeyEvent { e ->
        if (!interactive || e.type != KeyEventType.KeyDown) return@onKeyEvent false
        val dir = when (e.key) {
            Key.DirectionLeft -> Dir.Left
            Key.DirectionRight -> Dir.Right
            Key.DirectionUp -> Dir.Up
            Key.DirectionDown -> Dir.Down
            else -> null
        }
        when {
            dir != null -> {
                val m = moveCursor(cursor, dir, stepFor(e.nativeKeyEvent.repeatCount), session.windowWidthDp, session.windowHeightDp)
                cursor = m.at
                m.moved
            }
            e.key == Key.DirectionCenter || e.key == Key.Enter || e.key == Key.NumPadEnter -> { onPoint(cursor, null); true }
            else -> false
        }
    }
    val touches = if (!interactive) Modifier else Modifier
        .pointerInput(session) { detectTapGestures { o -> at(o)?.let { onPoint(it, null) } } }
        .pointerInput(session) {
            detectDragGestures(
                onDragStart = { o -> dragFrom = at(o) },
                onDrag = { change, _ ->
                    val a = dragFrom
                    val b = at(change.position)
                    if (a != null && b != null) areaOf(a, b)?.let { r -> onPoint(Point(r.x + r.width / 2, r.y + r.height / 2), r) }
                },
                onDragEnd = { dragFrom = null },
                onDragCancel = { dragFrom = null },
            )
        }

    Canvas(
        modifier
            .onSizeChanged { box = it }
            .semantics { contentDescription = "Frozen picture of the screen" }
            .then(if (interactive) Modifier.focusRequester(focus).onFocusChanged { focused = it.isFocused }.focusable().then(keys) else Modifier)
            .then(touches)
            .then(if (focused) Modifier.border(BorderStroke(2.dp, primary)) else Modifier),
    ) {
        val f = fit()
        val w = f.width.toInt()
        val h = f.height.toInt()
        if (w <= 0 || h <= 0) return@Canvas
        drawImage(image, dstOffset = IntOffset(f.offsetX.toInt(), f.offsetY.toInt()), dstSize = IntSize(w, h))
        val sx = f.width / session.windowWidthDp
        val sy = f.height / session.windowHeightDp
        fun px(p: Point) = Offset((f.offsetX + p.x * sx).toFloat(), (f.offsetY + p.y * sy).toFloat())
        val stroke = Stroke(width = 3f * density)
        region?.let { r ->
            drawRect(primary, topLeft = px(Point(r.x, r.y)), size = Size((r.width * sx).toFloat(), (r.height * sy).toFloat()), style = stroke)
        }
        if (region == null && tap != null) drawCircle(primary, radius = 14f * density, center = px(tap), style = stroke)
        if (session.television && interactive) {
            val c = px(cursor)
            val arm = 12f * density
            drawLine(Color.Red, Offset(c.x - arm, c.y), Offset(c.x + arm, c.y), strokeWidth = 2f * density)
            drawLine(Color.Red, Offset(c.x, c.y - arm), Offset(c.x, c.y + arm), strokeWidth = 2f * density)
        }
    }
}
