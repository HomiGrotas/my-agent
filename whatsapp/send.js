// Sends a WhatsApp text message to several recipients using whatsapp-web.js (WhatsApp Web automation).
//
// Usage:
//   node send.js --login         Link a WhatsApp account by scanning the QR code printed to the terminal, then exit
//   node send.js --list-groups   Print "<group id>\t<group name>" for every group the linked account is in
//   node send.js                 Read {"recipients": [...], "message": "...", "messages": {"<recipient>": "..."},
//                                "allGroups": true, "exclude": [...]} as JSON from stdin, send the message (or
//                                the recipient's own text from the optional "messages") to every recipient (a
//                                phone number or a "<id>@g.us" group ID) and, with "allGroups", to every group
//                                the linked account can post in except those in "exclude", and print
//                                {"<recipient>": null | "<error>"} as JSON to stdout
//   node send.js --bot           Run until stdin closes: print every private or group text message the linked
//                                account receives (also unread ones from before it started) as a JSON line
//                                {"chat": "<chat id>", "user": "<phone number or chat id>", "text": "..."} to
//                                stdout (group messages only if they tag the linked account, with the tag
//                                removed from "text"; "user" is then the group ID and "sender" the member), and execute the JSON lines read from stdin: {"to": "<chat id>",
//                                "text": "..."} sends a message, {"seen": "<chat id>"} marks the chat read
//
// The linked session is saved in WHATSAPP_SESSION_DIR (default: .wwebjs_auth next to this file), so the QR
// code only has to be scanned once. All logs go to stderr, stdout carries only the JSON result.

const path = require("path");
const readline = require("readline");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth, Message } = require("whatsapp-web.js");

// How long to wait for WhatsApp Web to be ready (includes the time to scan the QR code)
const READY_TIMEOUT_MS = 3 * 60 * 1000;
// How long to wait for the server to acknowledge each sent message before giving up on it
const ACK_TIMEOUT_MS = 30 * 1000;
// How often the bot looks for new private and group messages (the "message" event doesn't fire on current WhatsApp Web)
const POLL_INTERVAL_MS = 15 * 1000;
// How often the bot logs what WhatsApp Web holds, to tell "no messages arrive" from "messages are filtered out"
const STATUS_LOG_INTERVAL_MS = 5 * 60 * 1000;
// At most this many unread messages are read per unread chat, so busy groups (whose chatter stays unread) keep
// each poll cheap
const MAX_UNREAD_FETCH = 50;

const log = (...args) => console.error("[whatsapp]", ...args);

function readStdin() {
    return new Promise((resolve, reject) => {
        let data = "";
        process.stdin.setEncoding("utf8");
        process.stdin.on("data", (chunk) => (data += chunk));
        process.stdin.on("end", () => resolve(data));
        process.stdin.on("error", reject);
    });
}

function createClient() {
    const client = new Client({
        authStrategy: new LocalAuth({
            dataPath: process.env.WHATSAPP_SESSION_DIR || path.join(__dirname, ".wwebjs_auth"),
        }),
        // Cache the WhatsApp Web page next to this script, not in whatever directory we were started from
        webVersionCache: { type: "local", path: path.join(__dirname, ".wwebjs_cache") },
        puppeteer: {
            headless: true,
            // Uses PUPPETEER_EXECUTABLE_PATH when set (e.g. the system Chromium in Docker)
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
            args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        },
    });
    client.on("qr", (qr) => {
        log("Scan this QR code in WhatsApp > Linked devices > Link a device:");
        qrcode.generate(qr, { small: true }, (code) => console.error(code));
    });
    client.on("authenticated", () => log("Authenticated"));
    client.on("auth_failure", (message) => log("Authentication failure:", message));
    return client;
}

function waitForReady(client) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(
            () => reject(new Error("Timed out waiting for WhatsApp Web - run `node send.js --login` first")),
            READY_TIMEOUT_MS,
        );
        client.once("ready", () => {
            clearTimeout(timer);
            resolve();
        });
        client.once("auth_failure", (message) => {
            clearTimeout(timer);
            reject(new Error(`Authentication failure: ${message}`));
        });
        client.initialize().catch((error) => {
            clearTimeout(timer);
            reject(error);
        });
    });
}

// Newer WhatsApp Web builds no longer expose MsgKey._serialized, which whatsapp-web.js relies on
// (sendMessage then returns undefined and chat lookups fail). Restores it from toString(), as in
// the not-yet-merged upstream fix https://github.com/wwebjs/whatsapp-web.js/pull/201901
async function patchMsgKeySerialized(client) {
    await client.pupPage.evaluate(() => {
        const proto = window.require("WAWebMsgKey").prototype;
        if ("_serialized" in proto) return;
        Object.defineProperty(proto, "_serialized", {
            configurable: true,
            get() {
                return this.toString();
            },
            // Builds that still assign _serialized keep their own value
            set(value) {
                Object.defineProperty(this, "_serialized", {
                    value, writable: true, configurable: true, enumerable: true,
                });
            },
        });
    });
}

// Resolves once the server acknowledged the message, so closing the browser doesn't drop it
function waitForAck(client, message) {
    return new Promise((resolve, reject) => {
        if (message.ack >= 1) return resolve();
        const timer = setTimeout(() => {
            client.off("message_ack", onAck);
            reject(new Error("Timed out waiting for the message to be sent"));
        }, ACK_TIMEOUT_MS);
        const onAck = (acked, ack) => {
            if (acked.id.id !== message.id.id || ack < 1) return;
            clearTimeout(timer);
            client.off("message_ack", onAck);
            resolve();
        };
        client.on("message_ack", onAck);
    });
}

// Resolves a recipient (a phone number, a "<id>@g.us" group ID or a user's chat ID) to its WhatsApp chat ID
async function getChatId(client, recipient) {
    if (recipient.endsWith("@g.us")) {
        const chat = await client.getChatById(recipient).catch(() => null);
        if (!chat || !chat.isGroup) {
            throw new Error(`${recipient} is not a group this account is in`);
        }
        return chat.id._serialized;
    }
    // e.g. a "<id>@lid" bot subscriber whose phone number WhatsApp didn't reveal
    if (recipient.includes("@")) return recipient;
    const numberId = await client.getNumberId(recipient.replace(/\D/g, ""));
    if (!numberId) {
        throw new Error(`${recipient} is not registered on WhatsApp`);
    }
    return numberId._serialized;
}

// Returns the IDs of the groups the linked account is in and can post in (not ones it left, or where only
// admins may post and it isn't one)
async function getGroupIds(client) {
    return (await client.getChats())
        .filter((chat) => chat.isGroup && !chat.isReadOnly)
        .map((chat) => chat.id._serialized);
}

async function sendMessage(client, recipient, text) {
    const chatId = await getChatId(client, recipient);
    const message = await client.sendMessage(chatId, text, { linkPreview: true });
    if (!message) {
        throw new Error("WhatsApp Web didn't return the sent message, so its delivery is unknown");
    }
    await waitForAck(client, message);
}

// Returns a user's phone number for a private chat ID ("<number>@c.us", or a "<id>@lid" privacy ID if WhatsApp
// reveals its number), or the chat ID itself
async function getUserId(client, chatId) {
    if (chatId.endsWith("@lid")) {
        const [ids] = await client.getContactLidAndPhone([chatId]).catch(() => []);
        if (ids && ids.pn) chatId = ids.pn;
    }
    return chatId.endsWith("@c.us") ? chatId.split("@")[0] : chatId;
}

// Returns a mention's chat ID: mentions are "<id>@c.us" / "<id>@lid" strings, or ID objects on some builds
function getMentionId(mention) {
    if (typeof mention === "string") return mention;
    return mention._serialized || `${mention.user}@${mention.server}`;
}

async function runBot(client) {
    // The linked account's own chat IDs (its phone number and, if WhatsApp has one, its privacy ID), as group
    // messages tag it by either
    const me = client.info.wid._serialized;
    const [myIds] = await client.getContactLidAndPhone([me]).catch(() => []);
    const myChatIds = new Set([me, myIds && myIds.lid, myIds && myIds.pn].filter(Boolean));
    log(`Group commands must tag ${[...myChatIds].join(" / ")}`);
    // Messages are told apart by their WhatsApp message ID (id.id): messages serialized from the page lack
    // id._serialized on current WhatsApp Web builds
    const reported = new Set();
    const skipped = new Set();
    // Messages that weren't text yet (e.g. still encrypted), checked again on every poll
    const pending = new Set();
    async function report(message) {
        // Only private and group text messages from others (not statuses or the account's own messages)
        if (message.fromMe || !/@(c\.us|lid|g\.us)$/.test(message.from)) return;
        if (message.type !== "chat") {
            // e.g. "ciphertext" while WhatsApp Web can't decrypt it yet; logged once per type and message
            if (message.type === "ciphertext") pending.add(message.id.id);
            const key = `${message.id.id}:${message.type}`;
            if (!skipped.has(key)) {
                skipped.add(key);
                log(`Skipping a "${message.type}" message from ${message.from}`);
            }
            return;
        }
        pending.delete(message.id.id);
        // A message that arrives while the unread ones are being read would be reported twice
        if (reported.has(message.id.id)) return;
        reported.add(message.id.id);
        if (message.from.endsWith("@g.us")) {
            // In a group only messages that tag the linked account are for the bot, with the tag ("@<number>")
            // removed so the rest can be read as a command
            const myMentions = (message.mentionedIds || []).map(getMentionId).filter((id) => myChatIds.has(id));
            if (!myMentions.length) return;
            let text = message.body;
            for (const id of myMentions) text = text.split(`@${id.split("@")[0]}`).join(" ");
            // Commands in a group apply to the whole group, whichever member sent them
            const sender = message.author ? await getUserId(client, message.author) : null;
            process.stdout.write(JSON.stringify({ chat: message.from, user: message.from, sender, text: text.trim() }) + "\n");
            return;
        }
        const user = await getUserId(client, message.from);
        process.stdout.write(JSON.stringify({ chat: message.from, user, text: message.body }) + "\n");
    }

    // Commands run one at a time, in order
    let commands = Promise.resolve();
    const input = readline.createInterface({ input: process.stdin });
    input.on("line", (line) => {
        const command = JSON.parse(line);
        commands = commands.then(async () => {
            if (command.to) {
                const message = await client.sendMessage(command.to, command.text, { linkPreview: true });
                if (message) await waitForAck(client, message);
                log(`Replied to ${command.to}`);
            } else if (command.seen) {
                await client.sendSeen(command.seen);
            }
        }).catch((error) => log("Command failed:", error.message || error));
    });
    const closed = new Promise((resolve) => input.on("close", resolve));

    // Unread private and group chats, i.e. messages that arrived while the bot wasn't running. Handled chats are marked
    // read, and unread messages that aren't commands are already in `reported`, so each is reported once.
    async function reportUnread() {
        const unreadChats = await client.pupPage.evaluate(() =>
            window.require("WAWebCollections").Chat.getModelsArray()
                .filter((chat) => chat.unreadCount > 0)
                .map((chat) => [chat.id._serialized, chat.unreadCount]),
        );
        for (const [chatId, unreadCount] of unreadChats) {
            if (!/@(c\.us|lid|g\.us)$/.test(chatId)) continue;
            const chat = await client.getChatById(chatId);
            for (const message of await chat.fetchMessages({ limit: Math.min(unreadCount, MAX_UNREAD_FETCH) })) {
                await report(message);
            }
        }
    }

    // Messages received since the last check (by their timestamp, in seconds), read or not: the linked account
    // is someone's phone, where a chat that's open marks new messages read right away
    let since = Math.floor(Date.now() / 1000) - 60;
    async function reportNew() {
        const checkedAt = Math.floor(Date.now() / 1000);
        // Serialized in the page, as Chat.fetchMessages does (looking messages up by ID misses new ones)
        const messages = await client.pupPage.evaluate((since, pendingIds) =>
            window.require("WAWebCollections").Msg.getModelsArray()
                .filter((message) => !message.id.fromMe
                    && (message.t >= since || pendingIds.includes(message.id.id)))
                .map((message) => window.WWebJS.getMessageModel(message)),
        since, [...pending]);
        for (const data of messages) {
            const message = new Message(client, data);
            if (!reported.has(message.id.id)) await report(message);
        }
        since = checkedAt - 60; // overlap, for messages stamped slightly in the past; `reported` drops repeats
    }

    async function logStatus() {
        const status = await client.pupPage.evaluate(() => {
            const { Msg, Chat } = window.require("WAWebCollections");
            const messages = Msg.getModelsArray();
            const incoming = messages.filter((message) => !message.id.fromMe);
            const newest = Math.max(0, ...incoming.map((message) => message.t || 0));
            // Types of the incoming messages of the last 10 minutes, e.g. {"chat": 3, "ciphertext": 1}
            const recentTypes = {};
            for (const message of incoming) {
                if (message.t >= Date.now() / 1000 - 600) recentTypes[message.type] = (recentTypes[message.type] || 0) + 1;
            }
            // The newest few incoming messages' sender and type, to see why one wasn't reported
            const latest = incoming.slice().sort((a, b) => (b.t || 0) - (a.t || 0)).slice(0, 3)
                .map((message) => `${message.from && (message.from._serialized || String(message.from))}:${message.type}`);
            return { messages: messages.length, chats: Chat.getModelsArray().length, newestIncoming: newest, recentTypes, latest };
        });
        const newest = status.newestIncoming ? new Date(status.newestIncoming * 1000).toISOString() : "none";
        log(`Status: ${status.chats} chats, ${status.messages} messages loaded, newest incoming ${newest}, ` +
            `incoming in the last 10 min by type ${JSON.stringify(status.recentTypes)}, latest ${status.latest.join(" ")}, ` +
            `${reported.size} reported`);
    }

    // Kept in case the event works again; `reported` drops the duplicates
    client.on("message", (message) => report(message).catch((error) => log(error.message || error)));
    await reportUnread();
    await logStatus().catch(() => {});
    log("Listening for messages");
    let stopped = false;
    const poll = (async () => {
        let lastStatusLog = Date.now();
        while (!stopped) {
            await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
            if (stopped) break;
            await reportNew().catch((error) => log("Reading new messages failed:", error.message || error));
            await reportUnread().catch((error) => log("Reading unread chats failed:", error.message || error));
            if (Date.now() - lastStatusLog >= STATUS_LOG_INTERVAL_MS) {
                lastStatusLog = Date.now();
                await logStatus().catch((error) => log("Status failed:", error.message || error));
            }
        }
    })();
    await closed;
    stopped = true;
    await poll;
    await commands;
}

async function main() {
    const login = process.argv.includes("--login");
    const listGroups = process.argv.includes("--list-groups");
    const bot = process.argv.includes("--bot");
    const request = login || listGroups || bot ? null : JSON.parse(await readStdin());

    const client = createClient();
    // Close the browser cleanly when stopped, so the next run can reuse the session's browser profile
    process.once("SIGTERM", () => {
        log("Stopping");
        client.destroy().catch(() => {}).finally(() => process.exit(0));
    });
    try {
        await waitForReady(client);
        await patchMsgKeySerialized(client);
        log("Ready");
        if (login) return;
        if (bot) return await runBot(client);
        if (listGroups) {
            const groups = (await client.getChats()).filter((chat) => chat.isGroup);
            for (const group of groups) {
                process.stdout.write(`${group.id._serialized}\t${group.name}\n`);
            }
            return;
        }

        const recipients = [...request.recipients];
        if (request.allGroups) {
            const exclude = new Set(request.exclude || []);
            for (const groupId of await getGroupIds(client)) {
                if (!exclude.has(groupId) && !recipients.includes(groupId)) recipients.push(groupId);
            }
        }
        const results = {};
        for (const recipient of recipients) {
            try {
                const text = (request.messages || {})[recipient] ?? request.message;
                await sendMessage(client, recipient, text);
                results[recipient] = null;
                log(`Sent to ${recipient}`);
            } catch (error) {
                results[recipient] = error.message || String(error);
                log(`Failed to send to ${recipient}:`, results[recipient]);
            }
        }
        process.stdout.write(JSON.stringify(results));
    } finally {
        await client.destroy().catch(() => {});
    }
}

main().then(
    () => process.exit(0),
    (error) => {
        log(error.message || error);
        process.exit(1);
    },
);
