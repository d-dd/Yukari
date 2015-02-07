#Yukari Commands

* Yukari throttles commands on a by-user basis. She will ignore throttled users' commands. Currently it is only active for Cytube users, since IRC cannot be spammed as much. Each command has a 'cost' associated with it- the higher the cost the faster the user will hit the limit and become throttled. In general, commands that are more expensive to compute and commands connected to an external API have higher cost. Throtteld users must wait for their 'allowance' to fill back up. Most moderator commands such as `$omit` and `$replay` have a cost of 0.

##**General Commands:**
- `$greet` Greets the user. This is very important!
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
 `[-s {queue,q,add,a}] [-u USER] [-g GUEST]`  
 `[-n NUMBER] [-t TITLE] [-T TEMPORARY] [-N NEXT] [-r RECENT]`
  - `-s, --sample {queue,q,add,a,like,l}` `queue` (`q`), `add` (`a`), `like` (`l`) method of querying media from the database. `queue` searchs media that was ever queued by user. `add` searchs media that was first added, or introduced by user. `like` searches media that was liked by user.
 - `-u, --user USER` Cytube username.
 - `-r, --registered` True/False. Guests are not registered users.
 - `-n, --number` The limit for querying Media table. The maximum number for non-moderaters is 3, and 20 for moderators and above.
 - `-t` search by title
 - `-T, --temporary` add as temporary
 - `-N, --next` add as next
 - `-r, --recent` Includes the most recent queue in the search pool. By deafult this is set to false, meaning Yukari will exclude 200 of the most recently queued media.



##**CyTube PM Commands:**
- `$points`  Show points and basic user statistics. Adding and queuing media will generate more points. Staying in the channel will yield a small amount of points.  
- The stats are <b>a</b>dds, <b>q</b>ueues, <b>l</b>ikes (received), <b>d</b>islikes (received), <b>L</b>iked, <b>D</b>isliked
- `$read` Tell Yukari that I have read this.

##**CyTube Moderator commands:**
- `$manage` Set Yukari to manage the playlist. Yukari will continually queue videos (as temporary, at end) until the room is unoccupied by named users, the playlist is cleared, or manually cancelled (with `$manage`). 
- `points [user]` Retrieves points and stats information of `user`. `user` is assumed to be registered. Registered `user` not found in the database will return `0`'s.
- `$replay` Set the currently playing media to replay once. If Yukari detects a non-natural media or playlist change the replay will be cancelled.
- `$vote replay` Makes a poll asking users if the current media should be replayed. Needs at least 30 seconds of runtime left. Maximum poll time is 100 seconds. Ending the poll early or switching media manually will cancel the vote.
- `$repeat` Alias of `$replay`
- `$omit [type, id]` Add the omit flag to the specified media. If nothing is specified, the flag is applied to the currently playing media. Omitted media will not be selected by `$add`.
- `$unomit [type, id]` Remove omit flag.
- `$blacklist [type, id]` Add the blacklist flag to the specified media. If nothing is specified, the flag is appiled to the currently playing media. Blacklisted media will be deleted, and any subsequent queues will be automatically removed from the playlist.
- `$vocadb [VocaDB Song Id]` Match the currently playing media with a VocaDB Id. This will update the VocaDB Panel.
  -   `-f` Force update the cache #TODO
  -   `-p` PV match. Use this when the PV is the same as the entry in VocaDB (and not just the song). Without this the VocaDB panel will not display non-audio related artists such as illustrators and animators #TODO  


#####**experimental - use with care **
- `$reprint [smid]` Downloads a NicoNicoDouga video, and uploads it to Youtube. There is a delay of 5 minutes after the video has been uploaded before the video is automatically queued to the playlist, to allow Youtube to finish processing the video. Only admins who have been listed in `allowed.txt` can use this command. More information can be found at https://github.com/d-dd/Yukari/blob/master/connections/cytube/commands/loaders/README.md.
