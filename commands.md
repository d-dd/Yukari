#Yukari Commands
##**General Commands:**
- `$greet` Greets the user.
- `$bye` Says goodbye to the user.
- `$ask question` Answers Yes or No randomly to question.
- `$choose choices` Selects one choice from `choices`. `choices` may be separated by whitespace or commas.
- `$permute choices` Permutes `choices`. `choices` may be separated by whitespace or commas.
- `$anagram words` Returns an anagram of `words`. www.anagramgenius.com is the server that solves the anagrams.
- `$8ball question` Answers the question using a magic 8-ball.
- `$dice [rolls, sides]` Rolls dice and outputs sum. Rolls 1d6 without arguments. 
- `$uptime` Lists the uptimes of Yukari and other connected serviecs.
- `$sql` Execute a valid SQL command against Yukari's database directly.

##**CyTube Commands:**
- `$who` Chooses a Cytube user randomly 
- `$add` Queue media queried from the database.  
 `[-s {queue,q,add,a}] [-u USER] [-r REGISTERED]`  
 `[-n NUMBER] [-t TITLE] [-a ARTIST] [-T TEMPORARY] [-N NEXT]`
  - `-s, --sample {queue,q,add,a}` `queue` (`q`) or `add` (`a`) method of querying media from the database. `queue` searchs media that was ever queued by user. `add` searchs media that was first added, or introduced by user.
 - `-u, --user USER` Cytube username.
 - `-r, --registered` True/False. Guests are not registered users.
 - `-n, --number` The limit for querying Media table. The maximum number for non-moderaters is 3, and 20 for moderators and above.
 - `-t` search by title
 - `-a, --artist` #TODO
 - `-T, --temporary` add as temporary
 - `-N, --next` add as next

##**CyTube PM Commands:**
- `$points`  Show points. Adding and queuing media will generate more points. Staying in the channel will yield a small amount of points.  
- `$read` Tell Yukari that I have read this.

##**CyTube Moderator commands:**
- `$replay` Set the currently playing media to replay once. If Yukari detects a non-natural changeMedia, the replay will be cancelled.
- `$vote replay` Makes a poll asking users if the current media should be replayed. Needs at least 30 seconds of runtime left. Maximum poll time is 100 seconds. Ending the poll early or switching media manually will cancel the vote.
- `$repeat` Alias of `$replay`
- `$omit [type, id]` Add the omit flag to the specified media. If nothing is specified, the flag is applied to the currently playing media. Omitted media will not be selected by `$add`.
- `$unomit [type, id]` Remove omit flag.
- `$blacklist [type, id]` Add the blacklist flag to the specified media. If nothing is specified, the flag is appiled to the currently playing media. Blacklisted media will be deleted, and any subsequent queues will be automatically removed from the playlist.
- `$vocadb [VocaDB Song Id]` Match the currently playing media with a VocaDB Id. This will update the VocaDB Panel.
  -   `-f` Force update the cache #TODO
  -   `-p` PV match. Use this when the PV is the same as the entry in VocaDB (and not just the song). Without this the VocaDB panel will not display non-audio related artists such as illustrators and animators #TODO
