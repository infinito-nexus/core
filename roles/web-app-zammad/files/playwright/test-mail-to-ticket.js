const { test, expect, request } = require("@playwright/test");
const net = require("net");
const tls = require("tls");

const { decodeDotenvQuotedValue } = require("./personas");

const mailEnabled    = (decodeDotenvQuotedValue(process.env.EMAIL_SERVICE_ENABLED || "false") || "false").toLowerCase() === "true";
const smtpHost       = decodeDotenvQuotedValue(process.env.MAIL_SMTP_HOST || "");
const smtpPort       = Number(decodeDotenvQuotedValue(process.env.MAIL_SMTP_PORT || "0")) || 0;
const smtpUser       = decodeDotenvQuotedValue(process.env.MAIL_SMTP_USER || "");
const smtpPass       = decodeDotenvQuotedValue(process.env.MAIL_SMTP_PASS || "");
const helpdeskAddr   = decodeDotenvQuotedValue(process.env.HELPDESK_EMAIL || "");

async function smtpSend(host, port, user, pass, from, to, subject, body) {
  return new Promise((resolve, reject) => {
    let buf = "";
    const socket = net.connect(port, host);
    socket.setEncoding("utf8");
    socket.setTimeout(45_000, () => { socket.destroy(); reject(new Error("SMTP timeout")); });

    let stage = "banner";
    function send(cmd) { socket.write(cmd); }
    function consumeSmtpCode(code) {
      const ok = buf.split(/\r?\n/).some((line) => line.startsWith(`${code} `));
      if (!ok) return false;
      buf = "";
      return true;
    }

    socket.on("data", (chunk) => {
      buf += chunk;
      if (stage === "banner" && consumeSmtpCode(220)) {
        stage = "ehlo"; send(`EHLO playwright.infinito.example\r\n`);
      } else if (stage === "ehlo" && consumeSmtpCode(250)) {
        stage = "starttls"; send(`STARTTLS\r\n`);
      } else if (stage === "starttls" && consumeSmtpCode(220)) {
        const tlsSock = tls.connect({ socket, servername: host, rejectUnauthorized: false }, () => {
          stage = "tls-ehlo";
          tlsSock.write(`EHLO playwright.infinito.example\r\n`);
        });
        tlsSock.setEncoding("utf8");
        let tbuf = "";
        let tStage = "tls-ehlo";
        const checkSmtpCode = (c) => {
          const ok = tbuf.split(/\r?\n/).some((line) => line.startsWith(`${c} `));
          if (ok) tbuf = "";
          return ok;
        };
        tlsSock.on("data", (c) => {
          tbuf += c;
          if (tStage === "tls-ehlo" && checkSmtpCode(250)) {
            tStage = "auth"; tlsSock.write(`AUTH LOGIN\r\n`);
          } else if (tStage === "auth" && checkSmtpCode(334)) {
            tStage = "user"; tlsSock.write(`${Buffer.from(user).toString("base64")}\r\n`);
          } else if (tStage === "user" && checkSmtpCode(334)) {
            tStage = "pass"; tlsSock.write(`${Buffer.from(pass).toString("base64")}\r\n`);
          } else if (tStage === "pass" && checkSmtpCode(235)) {
            tStage = "mailfrom"; tlsSock.write(`MAIL FROM:<${from}>\r\n`);
          } else if (tStage === "mailfrom" && checkSmtpCode(250)) {
            tStage = "rcptto"; tlsSock.write(`RCPT TO:<${to}>\r\n`);
          } else if (tStage === "rcptto" && checkSmtpCode(250)) {
            tStage = "data"; tlsSock.write(`DATA\r\n`);
          } else if (tStage === "data" && checkSmtpCode(354)) {
            tStage = "body";
            const msg =
              `From: ${from}\r\n` +
              `To: ${to}\r\n` +
              `Subject: ${subject}\r\n` +
              `MIME-Version: 1.0\r\n` +
              `Content-Type: text/plain; charset=UTF-8\r\n` +
              `\r\n${body}\r\n.\r\n`;
            tlsSock.write(msg);
          } else if (tStage === "body" && checkSmtpCode(250)) {
            tStage = "quit"; tlsSock.write(`QUIT\r\n`);
          } else if (tStage === "quit" && checkSmtpCode(221)) {
            tlsSock.end();
            resolve();
          }
        });
        tlsSock.on("error", reject);
      }
    });
    socket.on("error", reject);
  });
}

exports.register = function (shared) {
  test("mail-to-ticket: SMTP send to helpdesk mailbox creates a Zammad ticket", async () => {
    test.skip(!mailEnabled, "Email service disabled in this variant");
    expect(smtpHost,     "MAIL_SMTP_HOST must be set when EMAIL_SERVICE_ENABLED=true").toBeTruthy();
    expect(smtpPort,     "MAIL_SMTP_PORT must be set").toBeTruthy();
    expect(smtpUser,     "MAIL_SMTP_USER must be set").toBeTruthy();
    expect(smtpPass,     "MAIL_SMTP_PASS must be set").toBeTruthy();
    expect(helpdeskAddr, "HELPDESK_EMAIL must be set").toBeTruthy();
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    const subject = `playwright-mail-${Date.now()}`;
    await smtpSend(
      smtpHost,
      smtpPort,
      smtpUser,
      smtpPass,
      smtpUser,
      helpdeskAddr,
      subject,
      "Email body from the Infinito.Nexus Playwright mail-to-ticket regression test."
    );

    const api = await request.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: {
        Authorization:
          `Basic ${ 
          Buffer.from(`${shared.env.adminUsername}:${shared.env.adminPassword}`).toString("base64")}`,
      },
    });

    // Force-fetch the IMAP inbound channel so we don't wait for the polling interval.
    const channelsResp = await api.get(`${shared.env.zammadBaseUrl}/api/v1/channels`);
    if (channelsResp.ok()) {
      const channels = await channelsResp.json();
      const emailChannel = channels.find?.((c) => c.area === "Email::Account");
      if (emailChannel) {
        await api.post(`${shared.env.zammadBaseUrl}/api/v1/channels/email_verify`, {
          data: { id: emailChannel.id, inbound: emailChannel.options?.inbound },
        }).catch(() => {});
      }
    }

    const deadline = Date.now() + 120_000;
    let found = null;
    while (Date.now() < deadline) {
      const searchResp = await api.get(
        `${shared.env.zammadBaseUrl}/api/v1/tickets/search?query=${encodeURIComponent(subject)}`
      );
      if (searchResp.ok()) {
        const result = await searchResp.json();
        const ids = Object.keys(result.assets?.Ticket ?? {});
        if (ids.length) { found = ids[0]; break; }
      }
      await new Promise((r) => setTimeout(r, 5_000));
    }

    await api.dispose();
    expect(found, `Expected a Zammad ticket with subject "${subject}" within 120s after SMTP send`).toBeTruthy();
  });
};
