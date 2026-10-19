package com.retroaura.lasrecomp

import android.app.Activity
import android.view.Gravity
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
                shoulder(2, NeoInputBridge.L, "L")
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
                single(9, NeoInputBridge.PLUS, "+"),
                shoulder(3, NeoInputBridge.R, "R")
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
        val half = FrameLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT)
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
                rightHost.layoutParams = rp
            }
        }
        val ll = FrameLayout.LayoutParams(1, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.START)
        val rr = FrameLayout.LayoutParams(1, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.END)
        view.addView(leftHost, ll)
        view.addView(rightHost, rr)
        leftHost.addView(left)
        rightHost.addView(right)
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
