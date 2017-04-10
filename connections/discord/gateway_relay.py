import asyncio
import json
import random

import discord
from discord.ext import commands

description = "gateway relay"
bot = commands.Bot(command_prefix='?', description=description)

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.event
async def on_message(message):
    transmittal = {'author': message.author.display_name,
                   'content': message.content,
                   'channel': message.channel.name}

    ts = json.dumps(transmittal) 

    loop = asyncio.get_event_loop()
    try:
        if loop.chatinstance:
            loop.chatinstance[0].send_data(ts.encode('utf8'))
    except(AttributeError):
        pass
        

clients = []
class SimpleChatProtocol(asyncio.Protocol):

    def __init__(self, server):
        self.server = server
        loop = asyncio.get_event_loop()
        loop.chatinstance = []
        loop.chatinstance.append(self)

    def connection_made(self, transport):
        self.transport = transport
        self.peername = transport.get_extra_info("peername")
        clients.append(self)

    def data_received(self, data):
        bot.say(data)
        for client in clients:
            if client is not self:
                client.transport.write("{}: {}".format(self.peername, data.decode()).encode())

    def send_data(self, data):
        #print("data_sent: {}".format(data.decode()))
        self.transport.write(data)

    def connection_lost(self, ex):
        print("connection_lost: {}".format(self.peername))
        clients.remove(self)

if __name__ == '__main__':
    with open('bot-token.conf') as f:
        token = f.readline().strip()
    try:
        loop = asyncio.get_event_loop()
        coro = loop.create_server(lambda: SimpleChatProtocol(''), port=8877)
        server = loop.run_until_complete(coro)

        for socket in server.sockets:
            print("serving on {}".format(socket.getsockname()))


        bot.loop.run_until_complete(bot.start(token))

    except KeyboardInterrupt:
        bot.loop.run_until_complete(bot.logout())
        pending = asyncio.Task.all_tasks(loop=bot.loop)
        gathered = asyncio.gather(*pending, loop=bot.loop)
        try:
            gathered.cancel()
            bot.loop.run_until_complete(gathered)

            # we want to retrieve any exceptions to make sure that
            # they don't nag us about it being un-retrieved.
            gathered.exception()
        except:
            pass
    finally:
        bot.loop.close()

