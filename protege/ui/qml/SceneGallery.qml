import QtQuick
import QtQuick.Controls
import Protege

// Also driven by tools/preview_scenes.py for repeatable, model-free captures.
Window {
    id: gallery
    width: 1440
    height: 810
    visible: true
    color: "#080e18"
    title: "Protégé — scene study"
    property string sceneName: "coast"
    property date sceneDate: new Date(2026, 6, 15, 14, 0)
    property string sceneWeather: "clear"
    property int sceneFrame: 0
    property bool animate: false
    property bool sceneLightning: false
    property bool sceneActive: true
    property alias sceneItem: sceneLoader.item
    Loader {
        id: sceneLoader
        anchors.fill: parent
        sourceComponent: gallery.sceneName === "space" ? orbital : coastal
    }
    Component {
        id: coastal
        BotanicaScene {
            active: gallery.sceneActive
            now: gallery.sceneDate
            weather: gallery.sceneWeather
            frameOverride: gallery.animate ? -1 : gallery.sceneFrame
            motion: gallery.animate ? 1 : 0
            lightningPreview: gallery.sceneLightning
        }
    }
    Component {
        id: orbital
        SpaceScene {
            active: gallery.sceneActive
            frameOverride: gallery.animate ? -1 : gallery.sceneFrame
            motion: gallery.animate ? 1 : 0
        }
    }
}
