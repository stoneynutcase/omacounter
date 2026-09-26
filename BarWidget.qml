pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar entry point: one "icon number" pair per counter, each in its own colour.
// Fetching, caching and the popup live in Panel.qml (loaded once, opened on
// click), mirroring the first-party weather widget and meteobar.
BarWidget {
  id: root
  moduleName: "stoneynutcase.omacounter"

  readonly property var panel: panelLoader.item

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = panelAnchor
    if ("hostWidget" in target) target.hostWidget = root
  }

  // The panel centres its card on its anchor. This widget sits in the bar's
  // right section, so its right edge is fixed while its left edge moves as
  // counters come and go; a zero-width anchor placed half a card left of
  // the right edge keeps the card right-aligned to the widget and still.
  Item {
    id: panelAnchor
    x: root.width - (root.panel ? root.panel.cardWidth : 0) / 2
    width: 0
    height: root.height
  }

  // refresh() is this instance only; refreshAll() reaches the copy on every
  // monitor. An IPC target routes to one handler, so anything that arrives
  // from outside (the CLI after add/remove/set, a keybind) must broadcast, or
  // the other bars keep showing the previous fetch until their timer fires.
  function refresh() {
    if (panel && panel.refresh) panel.refresh(true)
  }

  function refreshAll() {
    broadcast("refresh")
  }

  function togglePanel() {
    if (panel && panel.toggle) panel.toggle()
  }

  function notifySummary() {
    if (panel && panel.notifySummary) panel.notifySummary()
  }

  // Shape contract for shell.summon/hide/toggle routing (Bar.findPanelWidget
  // requires open/close/opened on the bar-widget root).
  readonly property bool opened: panel ? panel.opened === true : false

  function open() {
    if (panel && panel.open) panel.open()
  }

  function close() {
    if (panel && panel.close) panel.close()
  }

  readonly property bool popoutSwitchClosing: panel ? panel.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panel) panel.closeForPopoutSwitch()
  }

  // The open-panel underline should span the painted counters, not the slot.
  readonly property real openPanelIndicatorWidth: root.vertical ? verticalFace.implicitWidth : face.implicitWidth

  readonly property var entries: panel ? panel.barEntries : []
  readonly property bool hasEntries: entries.length > 0

  // ---- width budget ---------------------------------------------------------
  // Every counter is laid out, then as many as fit the budget stay visible,
  // in order, measured from their real rendered widths; the rest collapse
  // into a "+N" chip. Recomputed whenever the entries or a width change.
  // 0 = no budget.
  readonly property int maxWidth: panel ? Style.space(panel.barMaxWidth) : 0
  readonly property real pairGap: Style.space(10)
  property int fitCount: 1000000

  function recomputeFit() {
    var n = pairRepeater.count
    if (maxWidth <= 0 || root.vertical) {
      fitCount = n
      return
    }
    var used = 0
    for (var k = 0; k < n; k++) {
      var item = pairRepeater.itemAt(k)
      if (!item) return  // not laid out yet; the width change will call again
      // Reserve the chip's room whenever something would be left over.
      var chip = (k + 1 < n) ? pairGap + chipMetrics.advanceWidth * (1 + String(n - k - 1).length) : 0
      var next = used + (k > 0 ? pairGap : 0) + item.implicitWidth
      if (next + chip > maxWidth) {
        fitCount = k
        return
      }
      used = next
    }
    fitCount = n
  }

  TextMetrics { id: chipMetrics; font: chipText.font; text: "0" }

  onEntriesChanged: Qt.callLater(recomputeFit)
  onMaxWidthChanged: Qt.callLater(recomputeFit)

  readonly property var hiddenEntries: entries.slice(Math.min(fitCount, entries.length))

  readonly property string hiddenTooltip: {
    var lines = []
    for (var i = 0; i < hiddenEntries.length; i++) lines.push(Model.clip(hiddenEntries[i].label) + ": " + hiddenEntries[i].exact)
    return lines.join("\n")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // The label is painted by the rows below so every counter can carry its
    // own colour; WidgetButton still owns hover, tooltip, and click handling.
    labelVisible: false
    hasVisualContent: true
    fixedWidth: root.vertical ? -1 : face.implicitWidth + scaledHorizontalMargin * 2
    fixedHeight: root.vertical ? verticalFace.implicitHeight + scaledVerticalPadding * 2 : -1
    dimmed: !root.hasEntries || (root.panel ? root.panel.fetchBusy && !root.panel.hasData : true)
    // Horizontal bars get one tooltip per counter (below); the vertical face
    // shows a single counter, so the whole list is the useful tooltip there.
    tooltipText: root.vertical && root.panel ? root.panel.tooltipText : ""

    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.refreshAll()
      else if (b === Qt.RightButton) root.notifySummary()
      else root.togglePanel()
    }

    // Horizontal bars: counters side by side.
    Row {
      id: face
      visible: !root.vertical
      anchors.centerIn: parent
      spacing: Style.space(10)

      Repeater {
        id: pairRepeater
        model: root.hasEntries ? root.entries : [{ icon: "󰆙", text: "", iconColor: button.foreground, textColor: button.foreground, stale: false, tooltip: "Counters: click to add one" }]

        // A plain Item per counter (a positioner's children cannot carry
        // fill anchors, so the hover area lives on this wrapper, not on the
        // Row), holding the icon-and-number pair.
        Item {
          id: pair
          required property var modelData
          required property int index
          width: pairRow.implicitWidth
          height: pairRow.implicitHeight
          implicitWidth: pairRow.implicitWidth
          opacity: modelData.stale ? 0.6 : 1
          // Past the width budget: laid out for measuring, not shown.
          visible: index < root.fitCount
          onImplicitWidthChanged: Qt.callLater(root.recomputeFit)

          // Each counter is its own tooltip target. The bar checks this flag
          // before it shows, and anchors the tooltip to this item.
          readonly property bool tooltipHovered: pairHover.containsMouse

          function showOwnTooltip() {
            if (root.bar && pair.tooltipHovered) root.bar.showTooltip(pair, pair.modelData.tooltip || "")
          }

          MouseArea {
            id: pairHover
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton   // clicks fall through to the button
            // Deferred: the button's own hover handler runs in the same
            // event and clears tooltips; this show must land after it.
            onEntered: Qt.callLater(pair.showOwnTooltip)
            onExited: if (root.bar) root.bar.hideTooltip(pair)
          }

          Component.onDestruction: if (root.bar) root.bar.hideTooltip(pair)

          Row {
            id: pairRow
            spacing: Style.space(5)

            Text {
              textFormat: Text.PlainText
              text: pair.modelData.icon
              color: pair.modelData.iconColor
              font.family: button.fontFamily
              font.pixelSize: Style.font.icon
              renderType: Text.NativeRendering
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              visible: text !== ""
              textFormat: Text.PlainText
              text: pair.modelData.text
              color: pair.modelData.textColor
              font.family: button.fontFamily
              font.pixelSize: Style.font.body
              renderType: Text.NativeRendering
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }
      }

      // The overflow chip: "+N" for the counters that did not fit the width
      // budget. Hover lists them with their exact numbers; a click opens the
      // panel like the rest of the widget.
      Item {
        id: overflowChip
        visible: root.hiddenEntries.length > 0
        width: chipText.implicitWidth
        height: chipText.implicitHeight
        readonly property bool tooltipHovered: chipHover.containsMouse

        Text {
          id: chipText
          textFormat: Text.PlainText
          text: "+" + root.hiddenEntries.length
          color: button.foreground
          opacity: 0.6
          font.family: button.fontFamily
          font.pixelSize: Style.font.body
          renderType: Text.NativeRendering
        }

        MouseArea {
          id: chipHover
          anchors.fill: parent
          hoverEnabled: true
          acceptedButtons: Qt.NoButton
          onEntered: Qt.callLater(function() { if (root.bar && overflowChip.tooltipHovered) root.bar.showTooltip(overflowChip, root.hiddenTooltip) })
          onExited: if (root.bar) root.bar.hideTooltip(overflowChip)
        }

        Component.onDestruction: if (root.bar) root.bar.hideTooltip(overflowChip)
      }
    }

    // Vertical bars: icon over number, first (or cycling) counter only.
    Column {
      id: verticalFace
      visible: root.vertical
      anchors.centerIn: parent
      spacing: Style.space(2)

      readonly property var first: root.hasEntries ? root.entries[0] : null

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: verticalFace.first ? verticalFace.first.icon : "󰆙"
        color: verticalFace.first ? verticalFace.first.iconColor : button.foreground
        font.family: button.fontFamily
        font.pixelSize: Style.font.icon
        renderType: Text.NativeRendering
      }

      Text {
        visible: text !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: verticalFace.first ? verticalFace.first.text : ""
        color: verticalFace.first ? verticalFace.first.textColor : button.foreground
        font.family: button.fontFamily
        font.pixelSize: Style.font.caption
        renderType: Text.NativeRendering
      }
    }
  }
}
