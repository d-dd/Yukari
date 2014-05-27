#Yukari Commands

- `$Add` Queues media queried from the database.

 `[-s {queue,q,add,a}] [-u USER] [-r REGISTERED]`

 `[-n NUMBER] [-t TITLE] [-a ARTIST] [-T TEMPORARY] [-N NEXT]`
 
 - `-s, --sample {queue,q,add,a}` queue (q) or add (a) method of quering media from the database. queue will search media that was ever queued by user. add will search media that was first added, or introduced by user.
 - `-u, --user USER` Cytube username.
 - `-r, --registered` True/False. Guests are not registered users.
 - `-n, --number` The limit for querying Media table. It is not guaranteed that n media will be queued because there may not be enough matching media, some of those matches may already be on the playlist, and some media that are added may no longer be playable (e.g. deleted).
 - `-t` search by title cached in the Media table
 - `-a, --artist` todo
 - `-T, --temporary` add media as temporary
 - `-N, --next` add media as next
  
