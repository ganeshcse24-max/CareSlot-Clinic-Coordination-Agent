
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

const reportDateInput = $("reportDate");
if (reportDateInput) {
    const now = new Date();
    reportDateInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    reportDateInput.addEventListener("change", () => report());
}

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
let pendingRequest = "";
let chatContext = null;

const voiceButton = $("voiceButton");
const voiceStatus = $("voiceStatus");

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
        voiceStatus.textContent = event.error === "not-allowed"
            ? "Microphone permission was denied. Allow access in your browser and try again."
            : event.error === "no-speech"
                ? "No speech detected. Please try again."
                : "Voice recognition error: " + event.error;
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
        "Voice recognition is not supported by this browser. Please use Chrome.";
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

async function loadDoctors() {
    const container = $("doctorDirectory");
    try {
        const response = await fetch("/api/doctors");
        if (!response.ok) throw new Error("Doctor directory request failed");
        const data = await response.json();
        const groups = new Map();
        data.doctors.forEach(doctor => {
            if (!groups.has(doctor.specialty)) groups.set(doctor.specialty, []);
            groups.get(doctor.specialty).push(doctor);
        });
        container.replaceChildren();
        groups.forEach((doctors, specialty) => {
            const card = document.createElement("article");
            card.className = "doctor-card";
            const heading = document.createElement("h3");
            heading.textContent = specialty;
            const list = document.createElement("ul");
            doctors.forEach(doctor => {
                const item = document.createElement("li");
                item.textContent = doctor.name;
                list.appendChild(item);
            });
            card.append(heading, list);
            container.appendChild(card);
        });
    } catch (error) {
        container.textContent = "Unable to load the doctor directory.";
        console.error("Doctor directory loading error:", error);
    }
}


// ==============================
// CHAT ASSISTANT
// ==============================

async function sendMessage(message) {

    addBubble(message, "user");

    let combinedMessage = [pendingRequest, message].filter(Boolean).join(" ");
    const isGreeting = /^(hi|hello|hey|good morning|good afternoon|good evening)[!. ,]*$/i.test(message.trim());
    if (isGreeting) combinedMessage = message;
    const hasShortTime = /^(?:(?:make|book|schedule|reserve)\s+)?(?:it\s+)?(?:at|on)\s*(?:14|15|16|2|3|4)(?:\s*(?:am|pm))?[!. ,]*$/i.test(message.trim());
    const namesTarget = /\bdr\.?\s+[a-z]+\b|dermat|skin doctor|cardio|heart doctor|general medicine|family doctor/i.test(message);
    if (!pendingRequest && !namesTarget && !isGreeting && chatContext && Date.now() - chatContext.savedAt < 120000 &&
        /\b(?:book|make|schedule|reserve)\b/i.test(message) && chatContext.doctor) {
        combinedMessage = `Book ${chatContext.doctor} ${chatContext.date || ""} ${message}`;
    } else if (!pendingRequest && !namesTarget && !isGreeting && hasShortTime && chatContext &&
        Date.now() - chatContext.savedAt < 120000 && chatContext.doctor) {
        combinedMessage = `Book ${chatContext.doctor} ${chatContext.date || ""} ${message}`;
    }

    try {

        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ message: combinedMessage })
        });

        const data = await response.json();

        addBubble(
            data.reply || data.message,
            "bot"
        );

        // Keep the request only while the assistant is waiting for a detail.
        // This lets short replies such as "Dr. Priya" or "tomorrow at 3" work.
        const needsDetail = /which doctor|specify a time|provide your name|who should i add|include an appointment id|provide the appointment id/i.test(data.reply || "");
        if (!isGreeting) pendingRequest = needsDetail ? combinedMessage : "";
        if (data.context && data.context.doctor) {
            chatContext = { ...data.context, savedAt: Date.now() };
        } else if (data.action === "book" || data.action === "reschedule") {
            chatContext = null;
        }

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

        const selectedDate = $("reportDate")?.value || "";
        const reportUrl = selectedDate
            ? "/api/report?date=" + encodeURIComponent(selectedDate)
            : "/api/report";
        const response = await fetch(reportUrl);

        if (!response.ok) {
            throw new Error("Report request failed");
        }

        const data = await response.json();

        const container = $("reportBody");
        $("reportNote").textContent = data.utilisation_note;

        container.replaceChildren();

        const cards = [
            {
                title: data.booked,
                description: `Booked on ${data.date}`
            },
            {
                title: data.cancelled,
                description: "Cancelled that day"
            },
            {
                title: `${data.utilisation_pct}%`,
                description: `${data.booked} of ${data.capacity} daily slots used`
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

        data.utilisation_by_doctor.forEach(item => {
            const card = document.createElement("div");
            card.className = "risk-card";
            const title = document.createElement("b");
            title.textContent = item.doctor;
            const details = document.createElement("div");
            details.textContent = `${item.specialty} · ${item.booked}/${item.capacity} slots · ${item.utilisation_pct}% used`;
            card.append(title, details);
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

        const groups = new Map();
        rows.forEach(patient => {
            const key = patient.preferred_date || "any";
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(patient);
        });

        const dayKeys = [...groups.keys()].sort((a, b) =>
            a === "any" ? 1 : b === "any" ? -1 : a.localeCompare(b)
        );

        dayKeys.forEach(dayKey => {
            const dayRow = document.createElement("tr");
            dayRow.className = "waitlist-day-row";
            const dayHeading = document.createElement("th");
            dayHeading.colSpan = 7;
            if (dayKey === "any") {
                dayHeading.textContent = "Any day · no date preference";
            } else {
                const dayDate = new Date(`${dayKey}T00:00:00`);
                dayHeading.textContent = dayDate.toLocaleDateString(undefined, {
                    weekday: "long", year: "numeric", month: "long", day: "numeric"
                });
            }
            dayRow.appendChild(dayHeading);
            tbody.appendChild(dayRow);

            groups.get(dayKey).forEach(patient => {

            const tr = document.createElement("tr");

            const values = [
                patient.waitlist_id,
                patient.patient,
                patient.doctor,
                patient.preferred_date || "Not specified",
                patient.preferred_time || "Not specified",
                patient.status === "offered" ? "Offer needs approval" :
                    patient.status === "accepted" ? "Booked" : "Waiting"
            ];

            values.forEach((value, index) => {

                const td = document.createElement("td");
                if (index === 5) {
                    const status = document.createElement("span");
                    status.className = "pill" + (patient.status === "offered" ? " offered" : "");
                    status.textContent = value;
                    td.appendChild(status);
                } else {
                    td.textContent = value;
                }

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
loadDoctors();
report();
loadWaitlist();
