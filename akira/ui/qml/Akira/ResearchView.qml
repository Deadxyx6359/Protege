import QtQuick

Item {
    id: root
    signal sourceRequested(string error)
    signal artifactRequested(var artifact)
    signal permissionsRequested()

    function prepareInvestigation(text) { investigations.prepare(text); }

    InvestigationsView {
        id: investigations
        objectName: "researchInvestigations"
        anchors.fill: parent
        onSourceRequested: function (error) { root.sourceRequested(error); }
        onArtifactRequested: function (artifact) { root.artifactRequested(artifact); }
        onPermissionsRequested: root.permissionsRequested()
    }
}
