pragma Singleton
import QtQuick

/*!
    Where a clicked link goes.

    Every view that shows a reply hands its links here, and the window's one
    LinkPrompt answers them. Nothing is opened here: this only carries the
    address to the one place that shows it and asks.
*/
QtObject {
    /*! A link in a reply was clicked. */
    signal requested(string url)

    function ask(url) {
        const text = String(url).trim();
        if (text !== "")
            requested(text);
    }
}
