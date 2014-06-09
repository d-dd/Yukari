/*Upload this somewhere and put the link in External Javascript under
  Channel Settings, Admin Settings. */
var YUKARI = 'Yukarin'; //Put name here

//overwrite pm callback to silence private PMs
Callbacks.pm = function (data) {
    var name = data.username;
    if (IGNORED.indexOf(name) !== -1) {
        return;
    }
    //client sends commands Yukari (e.g. Clicking a button)
    if (name === CLIENT.name && data.to === YUKARI && data.msg.lastIndexOf('%%', 0) === 0) {
        return;
    }
    //Yukari sends special message to client (e.g. change button state)
    if (name === YUKARI && data.msg.lastIndexOf('%%', 0) === 0) { //starts with %%
        return;
    }
    if (data.username === CLIENT.name) {
        name = data.to;
    } else {
        pingMessage(true);
    }
    var pm = initPm(name);
    var msg = formatChatMessage(data, pm.data("last"));

    buffer.scrollTop(buffer.prop("scrollHeight"));
    if (pm.find(".panel-body").is(":hidden")) {
        pm.removeClass("panel-default").addClass("panel-primary");
    }
}

function enableLikes() {
    if (CLIENT.rank > -1) {
        $("#like-btn").attr('disabled', false);
        $("#dislike-btn").attr('disabled', false);
    }
}

function disableLikes() {
    var yukariLikeScore = 'unavailable';
    $("#likescore").text(yukariLikeScore);
    $("#like-btn").attr('disabled', true);
    $("#dislike-btn").attr('disabled', true);
}

function sendPmToYukari(message) {
    if (CLIENT.rank > -1) {
        socket.emit("pm", {
            "msg": message,
            "to": YUKARI
        });
    }
}

////create buttons
$("#likecontrol").remove();
$("#rightcontrols").append('<div id="likecontrol" class="btn-group-vertical"></div>');
$("#likecontrol").append('<button id="like-btn" class="btn btn-xs btn-default glyphicon glyphicon-chevron-up" ' +
    'data-toggle="button"><span id="like-btn-span"></span></button>');
$("#likecontrol").append('<button id="dislike-btn" class="btn btn-xs btn-default glyphicon glyphicon-chevron-down" ' +
    'data-toggle="button"><span id="dislike-btn-span"></span></button>');

//If Yukari isn't here, disable buttons
if (!findUserlistItem(YUKARI)) {
    disableLikes();
}

//When Yukari leaves, disable buttons
socket.on("userLeave", function (data) {
    if (data.name === YUKARI) {
        disableLikes();
    }
});


//When Yukari joins, enable buttons
socket.on("addUser", function (data) {
    if (data.name === YUKARI) {
        yukariLikeScore = 'unavailable';
        enableLikes();
    }
});

//span for +/-
$("#likescore").remove();
$("#rightcontrols").append('<span id="likescore" class="label label-primary">unavailable</span>');
$("#likescore").text(yukariLikeScore);


////hook events to buttons
$("#like-btn").click(function () {
    var isHere = findUserlistItem(YUKARI);
    var likeIsPressed = $("#like-btn").hasClass("active");
    var dislikeIsPressed = $("#dislike-btn").hasClass("active");
    //push the button!
    if (isHere && !likeIsPressed) {
        if (dislikeIsPressed) {
            $("#dislike-btn").removeClass("active");
            $("#dislike-btn").css("color", "");
        }
        sendPmToYukari("%%like");
        $("#like-btn").css("color", "Green");
    //unpush the button!
    } else if (isHere && likeIsPressed) {
        sendPmToYukari("%%unlike");
        $("#like-btn").css("color", "");
    }
});

$("#dislike-btn").click(function () {
    var isHere = findUserlistItem(YUKARI);
    var likeIsPressed = $("#like-btn").hasClass("active");
    var dislikeIsPressed = $("#dislike-btn").hasClass("active");
    //push the button!
    if (isHere && !dislikeIsPressed) {
        if (likeIsPressed) {
            $("#like-btn").removeClass("active");
            $("#like-btn").css("color", "");
        }
        sendPmToYukari("%%dislike");
        $("#dislike-btn").css("color", "Red");
        //unpush the button!
    } else if (isHere && dislikeIsPressed) {
        sendPmToYukari("%%unlike");
        $("#dislike-btn").css("color", "");
    }
});

////events on Yukari's PMs
//Yukari sends us PM
socket.on("pm", function (data) {
    if (data.username === YUKARI && data.msg === '%%1') {
        $("#like-btn").removeClass("active").addClass("active");
        $("#like-btn").css("color", "Green");
        $("#dislike-btn").removeClass("active");

    }
});

socket.on("pm", function (data) {
    if (data.username === YUKARI && data.msg === '%%-1') {
        $("#dislike-btn").removeClass("active").addClass("active");
        $("#dislike-btn").css("color", "Red");
        $("#like-btn").removeClass("active");
    }
});
//reset buttons on changeMedia
socket.on("changeMedia", function (data) {
    $("#like-btn").removeClass("active");
    $("#dislike-btn").removeClass("active");
    $("#like-btn").css("color", "");
    $("#dislike-btn").css("color", "");
});

//on channelCSSJS, update score span
socket.on("channelCSSJS", function (data) {
    if (findUserlistItem(YUKARI)) {
        $("#likescore").text(yukariLikeScore);
    }
});

////initialize
$("#like-btn").attr('disabled', true);
$("#dislike-btn").attr('disabled', true);

//send PM if not guest
if (CLIENT.rank > -1) {
    var isHere = findUserlistItem(YUKARI);
    if (isHere) {
        sendPmToYukari("%%subscribeLike");
        $("#like-btn").attr('disabled', false);
        $("#dislike-btn").attr('disabled', false);
    }
}

//send PM when log on/guest join
//this often skips for users already logged in because the script loads too late
socket.on("login", function (data) {
    var isHere = findUserlistItem(YUKARI);
    if (data.success === true && isHere) {
        sendPmToYukari("%%subscribeLike");
        $("#like-btn").attr('disabled', false);
        $("#dislike-btn").attr('disabled', false);
    }
});

//send PM when Yukari logs on
socket.on("addUser", function (data) {
    var isHere = findUserlistItem(YUKARI);
    if (data.name === YUKARI && isHere) {
        sendPmToYukari("%%subscribeLike");
    }
});
