package com.retroaura.lasrecomp

import android.content.Context
import android.view.Gravity
import android.view.KeyEvent
import android.widget.FrameLayout
import com.swordfish.radialgamepad.library.RadialGamePad
import com.swordfish.radialgamepad.library.config.*
import com.swordfish.radialgamepad.library.event.Event
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

/**
 * Real RadialGamePad widgets, using Neo's 12-sector Nintendo arrangement.
 * Optional Kotlin integration; do not instantiate without packaged dependencies.
 */
class NeoRadialController(context: Context) : FrameLayout(context) {
    private val bridge = NeoInputBridge()
    private val scope = CoroutineScope(Dispatchers.Main + Job())
    private fun button(id: Int, label: String) = ButtonConfig(id, label)
    private val left = RadialGamePad(
        RadialGamePadConfig(
            12,
            PrimaryDialConfig.Stick(NeoInputBridge.LEFT_STICK, 10001),
            listOf(
                SecondaryDialConfig.Cross(10, 3, 2.1f, .3f, CrossConfig(NeoInputBridge.DPAD_UP)),
                SecondaryDialConfig.SingleButton(9, 1f, .3f, button(NeoInputBridge.MINUS, "−")),
                SecondaryDialConfig.DoubleButton(2, .2f, button(NeoInputBridge.L, "L"))
            )
        ), 16f, context
    )
    private val right = RadialGamePad(
        RadialGamePadConfig(
            12,
            PrimaryDialConfig.PrimaryButtons(listOf(
                button(NeoInputBridge.A, "A"),
                button(NeoInputBridge.X, "X"),
                button(NeoInputBridge.Y, "Y"),
                button(NeoInputBridge.B, "B")
            )),
            listOf(
                SecondaryDialConfig.SingleButton(9, 1f, .3f, button(NeoInputBridge.PLUS, "+")),
                SecondaryDialConfig.DoubleButton(3, .2f, button(NeoInputBridge.R, "R"))
            )
        ), 16f, context
    )
    init {
        val leftHolder = FrameLayout(context)
        val rightHolder = FrameLayout(context)
        addView(leftHolder, LayoutParams(0, LayoutParams.MATCH_PARENT, 1f).apply { gravity = Gravity.LEFT })
        addView(rightHolder, LayoutParams(0, LayoutParams.MATCH_PARENT, 1f).apply { gravity = Gravity.RIGHT })
        // Width weights only work in LinearLayout; size each half on layout.
        addOnLayoutChangeListener { _, l, t, r, b, _, _, _, _ ->
            val half = (r - l) / 2
            leftHolder.layoutParams = (leftHolder.layoutParams as LayoutParams).apply { width = half; height = b-t }
            rightHolder.layoutParams = (rightHolder.layoutParams as LayoutParams).apply { width = half; height = b-t }
        }
        leftHolder.addView(left)
        rightHolder.addView(right)
        left.primaryDialMaxSizeDp = 200f
        right.primaryDialMaxSizeDp = 200f
        left.gravityX = -1f
        left.gravityY = 1f
        right.gravityX = 1f
        right.gravityY = 1f
        scope.launch { left.events().collect { handle(it) } }
        scope.launch { right.events().collect { handle(it) } }
    }
    private fun handle(event: Event) {
        when (event) {
            is Event.Button -> bridge.button(event.id, event.action == KeyEvent.ACTION_DOWN)
            is Event.Direction -> {
                if (event.id == NeoInputBridge.DPAD_UP) {
                    bridge.button(NeoInputBridge.DPAD_LEFT, event.xAxis < 0)
                    bridge.button(NeoInputBridge.DPAD_RIGHT, event.xAxis > 0)
                    bridge.button(NeoInputBridge.DPAD_UP, event.yAxis < 0)
                    bridge.button(NeoInputBridge.DPAD_DOWN, event.yAxis > 0)
                } else bridge.direction(event.id, event.xAxis, event.yAxis)
            }
            else -> Unit
        }
    }
    override fun onDetachedFromWindow() {
        bridge.releaseAll()
        scope.cancel()
        super.onDetachedFromWindow()
    }
}
