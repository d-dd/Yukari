Dependencies:
 google-api-python-client
 httplib2
 requests
 
Requirements:
NND account
 There is a way download videos without an account but I haven't explored that yet.
Youtube account
 The channel you want to upload to. It requires authentication with OAuth2.
 
First, make a file `allowed.txt` and put admin users who are allowed to use this command, separated by each line.
Then, grab a Google API account and make a file `client_secrets.json`. https://developers.google.com/api-client-library/python/guide/aaa_oaut has more details.
Run `reprinter.py`. On first run, it will ask you to authenticate a client. Follow the link. If your server doesn't have a web browser, copy the link onto another computer, and follow the prompts. Near the end it will redirect to another page, where it will time out (since it's not on the correct server). Copy paste the link, and back on the server, telnet a GET to that address. This will complete the flow process.

