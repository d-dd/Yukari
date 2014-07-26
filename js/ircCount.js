/*  Adds IRC usercount in the usercount hover tooltip.
    Requires a variable yukarIRC, which is supplied by Yukari
    via embedded javascript. */

//unbind the "mouseenter" bind on #usercount
$("#usercount").unbind("mouseenter");

//from sync/www/js/ui.js
//https://github.com/calzoneman/sync/blob/3.0/www/js/util.js
$("#usercount").mouseenter(function (ev) {
    var breakdown = calcUserBreakdown();
    //  start edit
    if (typeof yukarIRC != "undefined") {
        breakdown["IRC"] = yukarIRC;
        }
    // end edit
    // re-using profile-box class for convenience
    var popup = $("<div/>")
        .addClass("profile-box")
        .css("top", (ev.clientY + 5) + "px")
        .css("left", (ev.clientX) + "px")
        .appendTo($("#usercount"));

    var contents = "";
    for(var key in breakdown) {
        contents += "<strong>" + key + ":&nbsp;</strong>" + breakdown[key];
        contents += "<br>"
    }

    popup.html(contents);
});
