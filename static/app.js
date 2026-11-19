
const $ = id => document.getElementById(id);


// ==============================
// DATE AND CHAT HELPERS
// ==============================

$("today").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
});

function addBubble(text, who) {
    const el = document.createElement("div");
    el.className = "bubble " + who;
    el.textContent = text || "No response received.";

    $("chat").appendChild(el);
    $("chat").scrollTop = $("chat").scrollHeight;
}


// ==============================
// VOICE ASSISTANT
// ==============================

const chatForm = $("chatForm");
const messageInput = $("message");

// Find existing Speak buttons to prevent duplicates
const existingSpeakButtons = [
    ...chatForm.querySelectorAll("button")
].filter(button =>
    button.textContent.toLowerCase().includes("speak")
);

// Reuse the first existing Speak button
let voiceButton = existingSpeakButtons[0];

// Remove any extra Speak buttons
existingSpeakButtons.slice(1).forEach(button => button.remove());

// Create a Speak button only if one does not already exist
if (!voiceButton) {
    voiceButton = document.createElement("button");
    voiceButton.type = "button";
    voiceButton.textContent = "🎙 Speak";
    voiceButton.className = "secondary";

    const sendButton = chatForm.querySelector("button");

    if (sendButton) {
        chatForm.insertBefore(voiceButton, sendButton);
    } else {
        chatForm.appendChild(voiceButton);
    }
}

voiceButton.type = "button";
voiceButton.style.whiteSpace = "nowrap";

// Create or reuse the voice status message
let voiceStatus = document.getElementById("voiceStatus");

if (!voiceStatus) {
    voiceStatus = document.createElement("p");
    voiceStatus.id = "voiceStatus";
    voiceStatus.className = "muted";
    voiceStatus.style.marginTop = "10px";

    chatForm.insertAdjacentElement("afterend", voiceStatus);
}

voiceStatus.textContent =
    "Click Speak and say your appointment request.";

const SpeechRecognition =
    window.SpeechRecognition ||
    window.webkitSpeechRecognition;

let recognition = null;
let listening = false;

if (SpeechRecognition) {

    recognition = new SpeechRecognition();

    recognition.lang = "en-IN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        listening = true;
        voiceButton.textContent = "⏹ Stop listening";

        voiceStatus.textContent =
            "Listening... Please speak clearly.";
    };

    recognition.onresult = event => {
        const transcript =
            event.results[0][0].transcript;

        messageInput.value = transcript;

        voiceStatus.textContent =
            "Speech converted successfully. Review the text and click Send request.";
    };

    recognition.onerror = event => {
        voiceStatus.textContent =
            "Voice error: " + event.error +
            ". Please try again.";

        listening = false;
        voiceButton.textContent = "🎙 Speak";
    };

    recognition.onend = () => {
        listening = false;
        voiceButton.textContent = "🎙 Speak";
    };

    voiceButton.addEventListener("click", () => {

        if (listening) {
            recognition.stop();
            return;
        }

        try {
            recognition.start();
        } catch (error) {
            voiceStatus.textContent =
                "Voice recognition is starting. Please wait.";
        }
    });

} else {

    voiceButton.disabled = true;
    voiceButton.textContent = "Voice unavailable";

    voiceStatus.textContent =
        "Voice recognition is not supported. Please try Google Chrome.";
}


// ==============================
// LOAD DASHBOARD
// ==============================

async function load() {

    try {
        const response = await fetch("/api/dashboard");

        if (!response.ok) {
            throw new Error("Dashboard request failed");
        }

        const data = await response.json();

        $("total").textContent = data.total;
        $("booked").textContent = data.booked;
        $("cancelled").textContent = data.cancelled;
        $("waitlist").textContent = data.waitlist;

        $("rows").replaceChildren();

        data.appointments.forEach(appointment => {

            const tr = document.createElement("tr");

            const values = [
                "#" + appointment.id,
                appointment.patient,
                appointment.doctor,
                appointment.appt_date,
                appointment.appt_time,
                appointment.status
            ];

            values.forEach((value, index) => {

                const td = document.createElement("td");

                if (index === 5) {

                    const span = document.createElement("span");

                    span.className =
                        "pill " +
                        (appointment.status === "cancelled"
                            ? "cancelled"
                            : "");

                    span.textContent = value;

                    td.appendChild(span);

                } else {
                    td.textContent = value;
                }

                tr.appendChild(td);
            });

            const action = document.createElement("td");

            if (appointment.status === "booked") {

                const button = document.createElement("button");

                button.className = "small-btn";
                button.textContent = "Simulate reminder";

                button.addEventListener("click", () => {
                    remind(appointment.id);
                });

                action.appendChild(button);

            } else {
                action.textContent = "—";
            }

            tr.appendChild(action);
            $("rows").appendChild(tr);
        });

    } catch (error) {
        console.error("Dashboard loading error:", error);
    }
}


// ==============================
// CHAT ASSISTANT
// ==============================

async function sendMessage(message) {

    addBubble(message, "user");

    try {

        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ message })
        });

        const data = await response.json();

        addBubble(
            data.reply || data.message,
            "bot"
        );

        await Promise.all([
            load(),
            loadWaitlist(),
            report()
        ]);

    } catch (error) {

        addBubble(
            "Unable to connect to CareSlot server.",
            "bot"
        );

        console.error(error);
    }
}


// Send typed or converted voice request
chatForm.addEventListener("submit", event => {

    event.preventDefault();

    const message = messageInput.value.trim();

    if (message) {

        messageInput.value = "";

        sendMessage(message);
    }
});


// Quick action buttons
function quick(message) {
    sendMessage(message);
}


// ==============================
// SIMULATED REMINDER
// ==============================

async function remind(id) {

    try {

        const response = await fetch(
            `/api/remind/${id}`,
            { method: "POST" }
        );

        const data = await response.json();

        addBubble(data.message, "bot");

    } catch (error) {

        addBubble(
            "Unable to send simulated reminder.",
            "bot"
        );

        console.error(error);
    }
}


// ==============================
// DAILY OPERATIONS REPORT
// ==============================

async function report() {

    try {

        const response = await fetch("/api/report");

        if (!response.ok) {
            throw new Error("Report request failed");
        }

        const data = await response.json();

        const container = $("reportBody");

        container.replaceChildren();

        const cards = [
            {
                title: data.booked,
                description: "Active bookings"
            },
            {
                title: data.cancelled,
                description: "Cancelled bookings"
            }
        ];

        cards.forEach(item => {

            const card = document.createElement("div");
            card.className = "risk-card";

            const heading = document.createElement("b");
            heading.textContent = item.title;

            card.append(
                heading,
                document.createTextNode(item.description)
            );

            container.appendChild(card);
        });

        data.risk.forEach(item => {

            const card = document.createElement("div");
            card.className = "risk-card";

            const title = document.createElement("b");
            title.textContent =
                `${item.patient} · ${item.doctor}`;

            const details = document.createElement("div");
            details.textContent =
                `Appointment #${item.id}`;

            const score = document.createElement("strong");
            score.textContent =
                `${item.score}% demo risk`;

            const reason = document.createElement("div");
            reason.className = "muted";
            reason.textContent = item.reason;

            card.append(
                title,
                details,
                score,
                reason
            );

            container.appendChild(card);
        });

    } catch (error) {

        console.error("Report loading error:", error);
    }
}


// ==============================
// WAITLIST MANAGEMENT
// ==============================

async function loadWaitlist() {

    const tbody = $("waitlistTable");

    try {

        const response = await fetch("/api/waitlist");

        if (!response.ok) {
            throw new Error("Unable to load waitlist");
        }

        const data = await response.json();
        const rows = data.waitlist || [];

        tbody.replaceChildren();

        if (rows.length === 0) {

            const tr = document.createElement("tr");
            const td = document.createElement("td");

            td.colSpan = 7;
            td.textContent = "No patients in the waitlist.";

            tr.appendChild(td);
            tbody.appendChild(tr);

            return;
        }

        rows.forEach(patient => {

            const tr = document.createElement("tr");

            const values = [
                patient.waitlist_id,
                patient.patient,
                patient.doctor,
                patient.preferred_date || "Not specified",
                patient.preferred_time || "Not specified",
                patient.status
            ];

            values.forEach(value => {

                const td = document.createElement("td");
                td.textContent = value;

                tr.appendChild(td);
            });

            // Action column
            const action = document.createElement("td");

            if (patient.status === "offered") {

                const approveButton =
                    document.createElement("button");

                approveButton.className = "small-btn";
                approveButton.textContent = "Approve";

                approveButton.addEventListener("click", () => {
                    approveWaitlist(patient.waitlist_id);
                });

                const rejectButton =
                    document.createElement("button");

                rejectButton.className = "small-btn";
                rejectButton.textContent = "Reject";
                rejectButton.style.marginLeft = "6px";

                rejectButton.addEventListener("click", () => {
                    rejectWaitlist(patient.waitlist_id);
                });

                action.append(
                    approveButton,
                    rejectButton
                );

            } else {
                action.textContent = "—";
            }

            tr.appendChild(action);
            tbody.appendChild(tr);
        });

    } catch (error) {

        console.error("Waitlist loading error:", error);

        tbody.textContent = "Error loading waitlist.";
    }
}


// ==============================
// APPROVE WAITLIST OFFER
// ==============================

async function approveWaitlist(id) {

    if (!confirm(
        "Are you sure you want to approve this appointment offer?"
    )) {
        return;
    }

    try {

        const response = await fetch(
            `/api/waitlist/${id}/approve`,
            { method: "POST" }
        );

        const data = await response.json();

        addBubble(
            data.message || data.reply ||
            "Approval request completed.",
            "bot"
        );

        if (response.ok) {

            await Promise.all([
                load(),
                loadWaitlist(),
                report()
            ]);
        }

    } catch (error) {

        addBubble(
            "Unable to approve the waitlist offer.",
            "bot"
        );

        console.error(error);
    }
}


// ==============================
// REJECT WAITLIST OFFER
// ==============================

async function rejectWaitlist(id) {

    if (!confirm(
        "Are you sure you want to reject this offer?"
    )) {
        return;
    }

    try {

        const response = await fetch(
            `/api/waitlist/${id}/reject`,
            { method: "POST" }
        );

        const data = await response.json();

        addBubble(
            data.message || data.reply ||
            "Rejection request completed.",
            "bot"
        );

        if (response.ok) {

            await Promise.all([
                load(),
                loadWaitlist(),
                report()
            ]);
        }

    } catch (error) {

        addBubble(
            "Unable to reject the waitlist offer.",
            "bot"
        );

        console.error(error);
    }
}


// ==============================
// INITIAL LOAD
// ==============================

load();
report();
loadWaitlist();
