/*Upload this somewhere and put the link in External Javascript under
  Channel Settings, Admin Settings. */
var YUKARI = "Yukari"; //Put name here

var allowVdbLike = 2; // Number of failures before vdblike button is hidden

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
    var buffer = pm.find(".pm-buffer");
    msg.appendTo(buffer);
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

//Vocainfo parse
function groupArtists(artists) {
    var newArr = [],
        roles = {},
        newItem, i, j, cur;
    for (i = 0, j = artists.length; i < j; i++) {
        cur = artists[i];
        if (!(cur.role in roles)) {
            roles[cur.role] = {
                role: cur.role,
                name: []
            };
            newArr.push(roles[cur.role]);
        }
        roles[cur.role].name.push([cur.name, cur.id]);
    }
    return newArr;
}

function combineArtists(groupedArtists) {
    var artistString = '';
    for (i = 0, j = groupedArtists.length; i < j; i++) {
        cur = groupedArtists[i]
        var names = '',
            x, y, curname;
        for (x = 0, y = cur.name.length; x < y; x++) {
            curname = cur.name[x];
            names += '<a target ="_blank" href="http://vocadb.net/ar/' + curname[1] + '/">' + curname[0] + '</a>';
            if (x + 1 < y) {
                names += ', ';
            } else {
                names += '   ';
            }
        }
        artistString += cur.role + ': ' + names;
    }
    return artistString;
}

function combineTitles(titles) {
    var groupedTitles = '',
        i, j, cur;
    for (i = 0, j = titles.length; i < j; i++) {
        cur = titles[i];
        groupedTitles += cur;
        if (i + 1 < j) {
            groupedTitles += ' / ';
        }
    }
    return groupedTitles;
}

function makeBadge(songType) {
    var songLetter = '',
        label = 'label-primary';
    if (songType === 'Original') {
        songLetter = 'O';
    } else if (songType === 'Remaster') {
        songLetter = 'R';
    } else if (songType === 'Remix') {
        songLetter = 'R';
        label = 'label-default';
    } else if (songType === 'Cover') {
        songLetter = 'C';
        label = 'label-default';
    } else if (songType === 'Instrumental') {
        songLetter = 'I';
        label = 'label-default'; // Bootstrap 3 doesn't have label-inverse
    } else if (songType === 'Mashup') {
        songLetter = 'M';
        label = 'label-default';
    } else if (songType === 'MusicPV') {
        songLetter = 'PV';
        label = 'label-success';
    } else if (songType === 'DramaPV') {
        songLetter = 'D';
        label = 'label-success';
    } else {
        songLetter = 'o'
        label = 'label-default';
    }
    return [songLetter, label];
}

function setVocadb(groupedTitles, artistString) {
    $("#music-note-btn").removeClass("btn-default");
    $("#music-note-btn").addClass("btn-primary");
    $("#yukarin").remove();
    var songLetter = makeBadge(vocapack.vocadbInfo.songType);
    var badge = '   <a href="http://vocadb.net/S/' + vocapack.vocadbId +
        '/" target="_blank" style="text-decoration: none"><span id="songType-span" class="label ' + songLetter[1] + '">' + songLetter[0] + '</span></a>   ';
    if (allowVdbLike > 0) {
        //vdblike-outer: where button resides
        //vdblike-inner: display status message with .html
        var likeBtn = '<span id="vdblike-outer"><button id="vdblike-btn" class="btn btn-xs btn-default glyphicon glyphicon-star" ' +
            'data-toggle="button" title="Like on VocaDB!"><span id="vdblike-btn-span"></span></button><span id="vdblike-inner"></span></span>';
    } else {
        var likeBtn = "";
    }
    $("#vdb-div").append("<div id='yukarin'>" + groupedTitles + badge + likeBtn + "</br>" + artistString +
        "<a href='http://vocadb.net/S/" + vocapack.vocadbId + " ' target='_blank' title='link by: " + vocapack.setby + "</div>");

    //bind click
    $("#vdblike-btn").click(function () {
        console.log("Vdb-like " + vocapack.vocadbId);
        tryVdbLike(vocapack.vocadbId);
    });
}

function setBlankVocadb() {
    $("#music-note-btn").removeClass("btn-primary");
    $("#music-note-btn").addClass("btn-default");
    $("#yukarin").remove();
    $("#vdb-div").append("<div id='yukarin'>No match</div>");
}

function setVocadbPanel() {
    if (!findUserlistItem(YUKARI)) {
        console.log('setvocadbpanel if tri');
        setBlankVocadb();
        return;
    }

    $("#likescore").text(yukariLikeScore);
    if (yukariOmit) {
        $("#music-note-span").removeClass("glyphicon-music");
        $("#music-note-span").addClass("glyphicon-ban-circle");
    } else {
        $("#music-note-span").removeClass("glyphicon-ban-circle");
        $("#music-note-span").addClass("glyphicon-music");
    }
    if (vocapack.res) {
        console.log('setvocadbpanel if vocapack');
        var groupedArtists, artistString = '',
            groupedTitles = '';
        groupedArtists = groupArtists(vocapack.vocadbInfo.artists);
        artistString = combineArtists(groupedArtists);
        groupedTitles = combineTitles(vocapack.vocadbInfo.titles);
        setVocadb(groupedTitles, artistString);

    } else {
        setBlankVocadb();
    }
}

//VocaDB Like
function tryVdbLike(songId) {
    //Send GET request to URL to check whether the song is already liked/favorited
    // to avoid overwriting user preference. If there is no rating, it will like the song.
    var userVdbSongPreference = $.ajax({
        type: "GET",
        url: "http://vocadb.net/api/users/current/ratedSongs/" + songId,
        xhrFields: {
            withCredentials: true
        },
        dataType: "json"
    });

    userVdbSongPreference.fail(function (jqXHR, textStatus) {
        console.log("Request failed: " + textStatus);
        // "You're probably not logged in!"
        $("#vdblike-btn").attr("disabled", true);
        $("#vdblike-inner").html("<span class='server-whisper'>Error: Make sure you're logged in VocaDB.net</span>");
        allowVdbLike = allowVdbLike - 1;

    });

    userVdbSongPreference.done(function (res) {
        processVdbLike(res, songId);
    });
}

function processVdbLike(pref, songId) { //'Like', 'Favorite', 'Nothing'
    console.log(pref);
    if (pref === "Nothing") {
        console.log(songId + " No rating; let's like!");
        likeVdbSong(songId);
    } else if (pref == "Like") {
        console.log("already liked!");
        $("#vdblike-inner").html("<span class='server-whisper'>This song is already liked!</span>");
        $("#vdblike-btn").attr("disabled", true);
    } else if (pref == "Favorite") {
        console.log("This is favorited!");
        $("#vdblike-inner").html("<span class='server-whisper'>This song is favorited!</span>");
        $("#vdblike-btn").attr("disabled", true);
    }
}

// Don't use this directly because it can overwrite a favorite
function likeVdbSong(songId) {
    console.log("Liking song " + songId);
    $.ajax({
        type: "POST",
        url: "http://vocadb.net/api/users/current/ratedSongs/" + songId + "?rating=Like",
        xhrFields: {
            withCredentials: true
        },
        success: function () {
            console.log('likeVdbSong:ok');
            $("#vdblike-inner").html("<span class='server-whisper'>Liked! -Thank you for rating!</span>");
            $("#vdblike-btn").attr("disabled", true);

        },
        error: function () {
            console.log('likeVdbSong:error');
            $("#vdblike-inner").html("<span class='server-whisper'>Error at likeVdbSong [100]!</span>");
            allowVdbLike = allowVdbLike - 1;
            $("#vdblike-btn").attr("disabled", true);
        }
    });
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
        yukariLikeScore = "unavailable";
        enableLikes();
    }
});

////create buttons
$("#likecontrol").remove();
$("#rightcontrols").append('<div id="likecontrol" class="btn-group-vertical"></div>');
$("#likecontrol").append('<button id="like-btn" class="btn btn-xs btn-default glyphicon glyphicon-chevron-up" ' +
    'data-toggle="button"><span id="like-btn-span"></span></button>');
$("#likecontrol").append('<button id="dislike-btn" class="btn btn-xs btn-default glyphicon glyphicon-chevron-down" ' +
    'data-toggle="button"><span id="dislike-btn-span"></span></button>');

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
    if (data.username === YUKARI && data.msg === "%%1") {
        $("#like-btn").removeClass("active").addClass("active");
        $("#like-btn").css("color", "Green");
        $("#dislike-btn").removeClass("active");

    }
});

socket.on("pm", function (data) {
    if (data.username === YUKARI && data.msg === "%%-1") {
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
    setVocadbPanel();
});

//send PM when log on/guest join
//this often skips for users already logged in because the script loads too late
socket.on("login", function (data) {
    var isHere = findUserlistItem(YUKARI);
    if (data.success === true && isHere) {
        sendPmToYukari("%%subscribeLike");
        $("#like-btn").attr("disabled", false);
        $("#dislike-btn").attr("disabled", false);
    }
});

//send PM when Yukari logs on
socket.on("addUser", function (data) {
    var isHere = findUserlistItem(YUKARI);
    if (data.name === YUKARI && isHere) {
        sendPmToYukari("%%subscribeLike");
    }
});

//If Yukari isn't here, disable buttons
if (!findUserlistItem(YUKARI)) {
    disableLikes();
}

//span for +/-
$("#likescore").remove();
$("#rightcontrols").append(' <span id="likescore" class="label label-info">unavailable</span>');
$("#likescore").text(yukariLikeScore);

////initialize
$("#like-btn").attr("disabled", true);
$("#dislike-btn").attr("disabled", true);

//send PM if not guest
if (CLIENT.rank > -1) {
    var isHere = findUserlistItem(YUKARI);
    if (isHere) {
        sendPmToYukari("%%subscribeLike");
        $("#like-btn").attr("disabled", false);
        $("#dislike-btn").attr("disabled", false);
    }
}

//////////////VocaDB Info pane
//make Pane
$("#rightpane-inner").prepend('<div id="vdbcontrol" class="plcontrol-collapse col-lg-12 col-md-12 collapse" ' +
    'style="height: auto;"><div class="vertical-spacer"></div><div class="input-group">' +
    '<div id="vdb-div" class="well"></div></div></div>');
$("#plcontrol").append('<button id="music-note-btn" data-toggle="collapse" data-target="#vdbcontrol" ' +
    'class="btn btn-sm btn-default"><span id="music-note-span" ' +
    'class="glyphicon glyphicon-music" title="VocaDB"></span></button>');



//initial on join
setVocadbPanel();
