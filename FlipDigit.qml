import QtQuick
import qs.Commons

// One split-flap digit, built the way the real thing is.
//
// At rest the card shows two fixed halves: the top half of the current digit
// above the hinge, the bottom half below it. A flip is one leaf falling: the
// leaf holding the top half of the old digit swings forward and down through
// 180 degrees about the hinge. As it falls it uncovers the top half of the
// next digit that was waiting behind it, and when it lands its back face,
// printed with the bottom half of the next digit, covers the old bottom half.
//
// A card steps toward its target one leaf at a time, forward only, wrapping
// past 9 — 3 → 7 goes 4, 5, 6, 7 and 8 → 1 goes 9, 0, 1 — because a real
// drum only turns one way. The leaves on the way fall quickly; the last one
// falls slower and settles. A digit that changes mid-fall is
// picked up at the next leaf. Anything that is not a digit (the "?" of a
// missing value) flips straight to its target.
//
// `flipIn(delay)` resets the card to 0 and steps it up to its digit after
// `delay` ms — the first open of a session and a hard refresh, staggered per
// digit by the caller. A 0 asked to show 0 makes one full turn. With `snap`
// set, a changed digit is shown at once instead (rows being reordered).
//
// While `active` is false (the panel is closed) a changed digit is held
// rather than flipped, so the leaves fall where they can be seen: the card
// catches up the moment it becomes active again.
//
// The faces are opaque on purpose: a leaf only reads as a leaf when it hides
// what is behind it. The upper face is a shade lighter than the lower, the
// falling leaf darkens as it turns edge-on and brightens as it lands, and
// the old bottom half sinks into its shadow as the leaf comes down.
//
// A "," is a thousands gap, not a card: narrow, empty, never animated.
Item {
  id: root

  property string digit: "0"
  property bool active: true
  property color color: Color.foreground
  property string fontFamily: Style.font.family
  // Proportions of a classic flip clock card (digitalclock.live uses
  // 130×160 with an 80px digit): the digit is half the card's height and
  // the card is four fifths as wide as it is tall. One knob, the height,
  // sets all three; the font scale moves it with the rest of the shell.
  property real cardHeight: Style.space(22)
  property real cardWidth: Math.round(cardHeight * 0.8)
  property real fontSize: Math.round(cardHeight * 0.5)
  property real gapWidth: Style.space(4)
  property int halfDuration: 140       // each half of the landing leaf's fall
  property int stepHalfDuration: 48    // each half of a leaf on the way there

  readonly property bool gap: digit === ","
  readonly property real half: cardHeight / 2

  // Opaque faces mixed from the popup surface and the digit colour, so they
  // follow both the theme and a per-counter colour.
  function mix(base, tint, amount) {
    return Qt.rgba(base.r + (tint.r - base.r) * amount,
                   base.g + (tint.g - base.g) * amount,
                   base.b + (tint.b - base.b) * amount, 1)
  }
  readonly property color surface: Color.popups.background
  readonly property color faceTop: mix(surface, color, 0.20)
  readonly property color faceBottom: mix(surface, color, 0.13)
  readonly property color edgeColor: Util.alpha(color, 0.30)
  // The hinge is a faint hairline across the middle, nothing more: dark
  // enough to read as a crease, not enough to read as a gap. Opaque, so
  // the row never brightens when a leaf's edge passes underneath it.
  readonly property color hingeColor: mix(surface, color, 0.06)

  // `shown` is the digit on the card now; `next` is the leaf falling in.
  property string shown: digit
  property string next: digit
  property bool falling: false
  property real leafAngle: 0           // 0 at rest, -180 landed

  readonly property real progress: -leafAngle / 180
  readonly property bool pastEdge: leafAngle <= -90

  // The leaf in flight is the last one when it lands on the target.
  readonly property bool landing: next === digit
  readonly property int currentHalfDuration: landing ? halfDuration : stepHalfDuration

  width: gap ? gapWidth : cardWidth
  height: cardHeight

  // While `snap` is set a changed digit is shown at once, no leaf: the
  // caller is moving rows around, not changing numbers.
  property bool snap: false

  onDigitChanged: {
    if (gap) return
    if (snap) snapTo(digit)
    else if (active && digit !== shown) queueFlip()
  }
  onActiveChanged: if (active && !gap && digit !== shown) queueFlip()

  function snapTo(value) {
    fall.stop()
    introDelay.stop()
    falling = false
    leafAngle = 0
    shown = value
    next = value
  }

  function isDigit(s) {
    return s.length === 1 && s >= "0" && s <= "9"
  }

  // The next leaf on the way from `from` to `to`: one up, wrapping past 9,
  // when both are digits; straight to `to` otherwise.
  function stepToward(from, to) {
    if (!isDigit(from) || !isDigit(to)) return to
    return String((Number(from) + 1) % 10)
  }

  function queueFlip() {
    if (fall.running) return
    next = stepToward(shown, digit)
    fall.start()
  }

  function flipIn(delay) {
    if (gap) return
    fall.stop()
    falling = false
    leafAngle = 0
    shown = "0"
    next = "0"
    introDelay.interval = Math.max(1, delay)
    introDelay.restart()
  }

  Timer {
    id: introDelay
    interval: 1
    repeat: false
    onTriggered: root.queueFlip()
  }

  // One continuous fall, in two eased halves: the leaf accelerates as it
  // tips off the stop, then either keeps going (a step) or lands and bounces.
  SequentialAnimation {
    id: fall
    ScriptAction { script: { root.leafAngle = 0; root.falling = true } }
    NumberAnimation { target: root; property: "leafAngle"; from: 0; to: -90; duration: root.currentHalfDuration; easing.type: Easing.InQuad }
    // No bounce on landing: Qt draws the rotation with perspective, so a
    // leaf lifting off the bottom again is rendered fractionally larger and
    // its near edge spills a row over the hinge line.
    NumberAnimation {
      target: root; property: "leafAngle"; from: -90; to: -180
      duration: root.currentHalfDuration
      easing.type: root.landing ? Easing.OutCubic : Easing.OutQuad
    }
    ScriptAction {
      script: {
        root.shown = root.next
        root.falling = false
        root.leafAngle = 0
        // Not there yet, or a newer digit arrived mid-fall: next leaf.
        if (root.digit !== root.shown) Qt.callLater(root.queueFlip)
      }
    }
  }

  Rectangle {
    id: card
    visible: !root.gap
    anchors.fill: parent
    radius: Math.min(Style.cornerRadius, Math.round(root.cardHeight * 0.04) + 1)
    color: root.faceBottom
    border.width: 1
    border.color: root.edgeColor

    // Half a card: an opaque face with the glyph clipped to one half.
    // `upper` picks which half of the glyph is painted and which face colour
    // is used (Item already owns `top` as an anchor line). Placement is the
    // matching half of the card by default; the leaf's faces override it.
    // `shade` darkens the face toward the surface colour.
    component Face: Item {
      id: face
      property string text: ""
      property bool upper: true
      property real shade: 0
      x: 1
      y: upper ? 1 : root.half
      width: card.width - 2
      height: root.half - 1
      clip: true

      Rectangle {
        anchors.fill: parent
        color: face.upper ? root.faceTop : root.faceBottom
      }

      // The crease: the bottom row of every upper face, painted under the
      // glyph so a digit's middle stroke (5, 6, 3, 8, 9) stays whole.
      Rectangle {
        visible: face.upper
        x: 0
        y: face.height - 1
        width: face.width
        height: 1
        color: root.hingeColor
      }

      Text {
        textFormat: Text.PlainText
        text: face.text
        color: root.color
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: true
        x: (face.width - implicitWidth) / 2
        y: (root.cardHeight - implicitHeight) / 2 - (face.upper ? 1 : root.half)
      }

      Rectangle {
        anchors.fill: parent
        color: root.surface
        opacity: Math.max(0, Math.min(1, face.shade))
      }
    }

    // The fixed halves. The upper one shows the next digit as soon as a leaf
    // starts to fall (that is what the leaf uncovers); the lower one keeps
    // the old digit until the leaf lands on it, sinking into shadow first.
    Face {
      text: root.falling ? root.next : root.shown
      upper: true
    }
    Face {
      text: root.shown
      upper: false
      // Fully dark by the time the leaf is edge-on: the old digit's lower
      // half must be gone before the new face lands, or a glyph feature on
      // the centre line (the dot of a dotted zero) lingers under the hinge.
      shade: root.falling ? Math.min(1, root.progress * 2) : 0
    }

    // The leaf. It starts as the upper half and is hinged on its bottom edge,
    // which is the card's centre line. Its front carries the top half of the
    // old digit; its back, pre-mirrored so it reads upright once the leaf
    // has turned over, carries the bottom half of the new digit. Past
    // edge-on the front is hidden and the back is shown.
    Item {
      id: leaf
      // Hidden around edge-on, and for much longer on the way out than on
      // the way in. Past the edge the back face grows out from the hinge,
      // so its far end (the base bar of a "1") starts on the centre line
      // and travels down to the bottom; on a slow landing leaf that reads
      // as a bar sliding across the card. By -155° the face is nine tenths
      // open and the digit appears where it belongs, with just the last
      // stretch and the bounce left to see.
      visible: root.falling && (root.leafAngle > -75 || root.leafAngle < -155)
      x: 1
      y: 1
      width: card.width - 2
      height: root.half - 1
      // Not rendered through a layer: a layer here flattens the back face's
      // mirror transform, so the landing leaf shows its digit upside down.
      transform: Rotation {
        origin.x: leaf.width / 2
        origin.y: leaf.height
        axis { x: 1; y: 0; z: 0 }
        angle: root.leafAngle
      }

      Face {
        visible: !root.pastEdge
        text: root.shown
        upper: true
        x: 0
        y: 0
        shade: 0.9 * Math.pow(Math.min(1, root.progress * 2), 1.5)
      }

      // Shading is steep on purpose: a face seen at a glancing angle is
      // foreshortened against the hinge, and a bright glyph squeezed into
      // those few rows reads as a flash at the centre of the card. Both
      // faces are nearly black at edge-on and clear only as they flatten.
      Face {
        visible: root.pastEdge
        text: root.next
        upper: false
        x: 0
        y: 0
        shade: 0.9 * Math.pow(Math.max(0, 2 - root.progress * 2), 1.5)
        transform: Scale {
          origin.y: (root.half - 1) / 2
          yScale: -1
        }
      }
    }

    // While a leaf moves, the hinge row is masked from above: a folding
    // face is squeezed toward the centre line and whatever bright pixels
    // it carries near its edge (the dot of a zero) would surface there.
    // At rest this is off, so the crease stays under the digit.
    Rectangle {
      visible: root.falling
      x: 1
      width: card.width - 2
      y: root.half - 1
      height: 1
      color: root.hingeColor
    }
  }
}
