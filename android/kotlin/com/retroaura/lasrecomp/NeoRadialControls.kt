package com.retroaura.lasrecomp

import android.app.Activity
import android.view.Gravity
import android.view.MotionEvent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.widget.Button
import android.view.KeyEvent
import android.view.ViewGroup
import android.widget.FrameLayout
import com.swordfish.radialgamepad.library.RadialGamePad
import com.swordfish.radialgamepad.library.config.ButtonConfig
import com.swordfish.radialgamepad.library.config.CrossConfig
import com.swordfish.radialgamepad.library.config.PrimaryDialConfig
import com.swordfish.radialgamepad.library.config.RadialGamePadConfig
import com.swordfish.radialgamepad.library.config.SecondaryDialConfig
import com.swordfish.radialgamepad.library.event.Event
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

/**
 * Original Swordfish90 RadialGamePad components, configured like Ryujinx Neo.
 * Requires the original GPL-3.0-or-later library, not a drawn approximation.
 * Compile this Kotlin file and its transitive dependencies before enabling it.
 */
class NeoRadialControls(private val activity: Activity, private val input: NeoInputBridge) {
    private val scope = CoroutineScope(Dispatchers.Main + Job())
    private val left: RadialGamePad
    private val right: RadialGamePad
    val view: FrameLayout = FrameLayout(activity)

    private fun button(id: Int, label: String) = ButtonConfig(id, label)
    private fun single(index: Int, id: Int, label: String) =
        SecondaryDialConfig.SingleButton(index, 1f, 0.3f, button(id, label))
    private fun shoulder(index: Int, id: Int, label: String) =
        SecondaryDialConfig.DoubleButton(index, 0.2f, button(id, label))

    init {
        val leftConfig = RadialGamePadConfig(
            12,
            PrimaryDialConfig.Stick(NeoInputBridge.LEFT_STICK, 10001),
            listOf(
                SecondaryDialConfig.Cross(10, 3, 2.1f, 0.3f,
                    CrossConfig(NeoInputBridge.DPAD_UP)),
                single(9, NeoInputBridge.MINUS, "−"),
                shoulder(2, NeoInputBridge.L, "L"),
                SecondaryDialConfig.DoubleButton(2, 1f, button(NeoInputBridge.ZL, "ZL")),
                single(1, NeoInputBridge.LEFT_STICK_BUTTON, "L3")
            )
        )
        val rightConfig = RadialGamePadConfig(
            12,
            PrimaryDialConfig.PrimaryButtons(listOf(
                button(NeoInputBridge.A, "A"),
                button(NeoInputBridge.X, "X"),
                button(NeoInputBridge.Y, "Y"),
                button(NeoInputBridge.B, "B")
            )),
            listOf(
                SecondaryDialConfig.Stick(6, 3, 2.7f, 0.3f,
                    NeoInputBridge.RIGHT_STICK, 10002),
                single(9, NeoInputBridge.PLUS, "+"),
                shoulder(3, NeoInputBridge.R, "R"),
                SecondaryDialConfig.DoubleButton(3, 1f, button(NeoInputBridge.ZR, "ZR")),
                single(5, NeoInputBridge.RIGHT_STICK_BUTTON, "R3")
            )
        )
        left = RadialGamePad(leftConfig, 16f, activity)
        right = RadialGamePad(rightConfig, 16f, activity)
        left.primaryDialMaxSizeDp = 200f
        right.primaryDialMaxSizeDp = 200f
        left.gravityX = -1f
        left.gravityY = 1f
        right.gravityX = 1f
        right.gravityY = 1f

        val leftHost = FrameLayout(activity)
        val rightHost = FrameLayout(activity)
        // Use measured half-screen widths rather than a zero-width layout.
        view.addOnLayoutChangeListener { _, l, _, r, _, _, _, _, _ ->
            val width = (r - l) / 2
            val lp = leftHost.layoutParams as FrameLayout.LayoutParams
            if (lp.width != width) {
                lp.width = width
                leftHost.layoutParams = lp
            }
            val rp = rightHost.layoutParams as FrameLayout.LayoutParams
            if (rp.width != width) {
                rp.width = width
                rp.gravity = Gravity.END
                rightHost.layoutParams = rp
            }
        }
        val ll = FrameLayout.LayoutParams(1, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.START)
        val rr = FrameLayout.LayoutParams(1, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.END)
        view.addView(leftHost, ll)
        view.addView(rightHost, rr)
        leftHost.addView(left, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        rightHost.addView(right, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        // Neo itself has no HOME in GamePadButtonInputId. This small host
        // control opens the actual LASRecomp in-game settings with SDL F1.
        // Keep it outside both radial areas to avoid stealing gamepad touches.
        val d = activity.resources.displayMetrics.density
        val home = Button(activity).apply {
            text = "HOME"
            textSize = 12f
            isAllCaps = false
            setTextColor(Color.WHITE)
            background = GradientDrawable().apply {
                setColor(Color.argb(196, 37, 43, 52))
                cornerRadius = 15f * d
                setStroke((1f * d).toInt().coerceAtLeast(1),
                    Color.argb(208, 188, 200, 212))
            }
            setOnTouchListener { v, ev ->
                when (ev.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        input.home(true)
                        true
                    }
                    MotionEvent.ACTION_UP -> {
                        input.home(false)
                        v.performClick()
                        true
                    }
                    MotionEvent.ACTION_CANCEL -> {
                        input.home(false)
                        true
                    }
                    else -> true
                }
            }
        }
        val homeLayout = FrameLayout.LayoutParams(
            (76f * d).toInt(), (38f * d).toInt(),
            Gravity.TOP or Gravity.RIGHT
        ).apply {
            topMargin = (10f * d).toInt()
            rightMargin = (16f * d).toInt()
        }
        view.addView(home, homeLayout)

        scope.launch { left.events().collect { dispatch(it) } }
        scope.launch { right.events().collect { dispatch(it) } }
    }

    private fun dispatch(event: Event) {
        when (event) {
            is Event.Button -> input.button(event.id, event.action == KeyEvent.ACTION_DOWN)
            is Event.Direction -> input.direction(event.id, event.xAxis, event.yAxis)
        }
    }

    fun close() {
        scope.cancel()
        input.releaseAll()
    }
}
