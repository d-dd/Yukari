#Yukari - A CyTube Bot
## Commands
A list of commands can be found at https://github.com/d-dd/Yukari/blob/master/commands.md
## About
Yukari is a CyTube bot written for a Vocaloid channel. Thus some of the features will be unnecessary for most channels.
For a general purpose bot, consider using NuclearAce's https://github.com/nuclearace/CytubeBot.
However, you can always delete (or prefix a plugin filename with `_`) a plugin file to prevent Yukari from importing the plugin.


##**Dependencies:**  
Python 2.x  
Twisted  
Twisted Autobahn

##**Requirements:**  
A CyTube server to connect to   
An account with admin rank or higher (3+) in the channel Yukari will run.

##**Installation:**  
Create the SQLite database:
<pre>python createDb.py</pre>
Edit the settings.cfg.  
Edit ext/external.js and upload it somewhere. If the channel already has custom js, just copy-paste the contents.

#### In CyTube
Yukari needs to have admin rank or higher (3+) because she modifies the channel javascript frequently.  
Set a filter: <pre>@3939([^`]+)#3939, g, <span class="server-whisper">$1</span></pre>  

This is for the gray server-like messages when users queue media to the playlist, and when Yukari removes something from the playlist.  
Edit italics filter: <pre>(^| )\_([^\_].+?[^\_])\_($| ), g, \\1\<em\>\\2\</em\>\\3</pre>
Set a filter: <pre>__, g, _</pre>

Put the url of external.js into the external JS box.

##**Usage:**
`Tacfile.py` is a Twisted application file that can be run with `twistd`.
For example, <pre>twistd -noy tacfile.py</pre>
Yukari is being developed and tested in a Linux environment, so it may have problems running on Windows or Mac.

##**Telnet:**  
<pre>telnet localhost [port]</pre>
Uses Twisted's Manhole module to access Yukari's names directly.
This is very useful for debugging. The instance of Yukari is `y`, so for example, `dir(y)` will list all of her names and `y.sendChats('Hello!')` will send messages to CyTube and IRC (if connected).

##Optional  
Youtube v3 API key  
IRC account

###Features
Yukari is similar to Desuwa's CyNaoko in terms of capabilities, and many of the features are a direct port of CyNaoko.  

- Modular setup  
Yukari's main connection modules are set up to be mostly interfaces. They contain the most important functionality, such as connect, disconnect, reconnect, database logging, and chat relay. Features such as commands and media checking are done by plugins, which work independent of other plugins, and can be easily added or removed to extend Yukari's capabilities. You can extend your own custom commands and features by adding your own plugin file, and it will be imported at runtime without having to change any of Yukari's code.

- IRC Bridge  
Relays chat between CyTube and IRC. Depending on the IRC netowrk, chat may be heavily throttled. Changing the bucketSize in the settings.cfg may be required if Yukari stop relaying too often, or ever gets kicked or throttled by the IRC network.

- VocaDB panel
Uses VocaDB.net's API service to display song information under the video.

- Media management  
Yukari saves each media that is queued to the playlist. If it is a Youtube video, it is checked against Youtube's API to make sure it is playable in CyTube. `$omit` and `$blacklist` reduces moderator work.

- Media feedback  
Users can vote (like/dislike) media in the playlist. This is useful for gathering channel preferences.

- Database logging  
User actions such as queueing, chatting, joining, leaving, liking, disliking are logged to the database. This can be analyzed for channel statistics and user behavior, and finding out which users are contributing to the channel the most.

###Main Differences from CyNaoko
- Yukari is written using Twisted, an asynchronous framework for Python. As a result Yukari uses fewer threads. Twisted uses one thread, and the adbapi uses another for accessing the SQLite database. 
- Each connection to a service is separated so when one goes down the whole program does not need to restart.  
- The database is more normalized, which allows for more interesting (which may or may not be useful) queries.
