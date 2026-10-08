// Sends a WhatsApp text message to several recipients using whatsapp-web.js (WhatsApp Web automation).
//
// Usage:
//   node send.js --login   Link a WhatsApp account by scanning the QR code printed to the terminal, then exit
//   node send.js           Read {"recipients": [...], "message": "..."} as JSON from stdin, send the message to
//                          every recipient, and print {"<recipient>": null | "<error>"} as JSON to stdout
//
// The linked session is saved in WHATSAPP_SESSION_DIR (default: .wwebjs_auth next to this file), so the QR
// code only has to be scanned once. All logs go to stderr, stdout carries only the JSON result.

const path = require("path");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

// How long to wait for WhatsApp Web to be ready (includes the time to scan the QR code)
const READY_TIMEOUT_MS = 3 * 60 * 1000;
// How long to wait for the server to acknowledge each sent message before giving up on it
const ACK_TIMEOUT_MS = 30 * 1000;

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

// Resolves once the server acknowledged the message, so closing the browser doesn't drop it
function waitForAck(client, message) {
    return new Promise((resolve, reject) => {
        if (message.ack >= 1) return resolve();
        const timer = setTimeout(() => {
            client.off("message_ack", onAck);
            reject(new Error("Timed out waiting for the message to be sent"));
        }, ACK_TIMEOUT_MS);
        const onAck = (acked, ack) => {
            if (acked.id._serialized !== message.id._serialized || ack < 1) return;
            clearTimeout(timer);
            client.off("message_ack", onAck);
            resolve();
        };
        client.on("message_ack", onAck);
    });
}

async function sendMessage(client, recipient, text) {
    const number = recipient.replace(/\D/g, "");
    const numberId = await client.getNumberId(number);
    if (!numberId) {
        throw new Error(`${recipient} is not registered on WhatsApp`);
    }
    const message = await client.sendMessage(numberId._serialized, text, { linkPreview: true });
    await waitForAck(client, message);
}

async function main() {
    const login = process.argv.includes("--login");
    const request = login ? null : JSON.parse(await readStdin());

    const client = createClient();
    try {
        await waitForReady(client);
        log("Ready");
        if (login) return;

        const results = {};
        for (const recipient of request.recipients) {
            try {
                await sendMessage(client, recipient, request.message);
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
