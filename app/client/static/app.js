/**
 * Qlaude client application.
 *
 * Manages session list, conversation history, feature toggles, SSE
 * streaming, user authentication state, quota tracking, and error
 * display from the API server (port 5000).
 */

let active_session = "", think = false, search = false, file = "";

// ── User state (populated from /api/user on load) ───────────────────
let currentUser = null;
let currentQuota = null;



let textArea = () => {
    let myTextarea = document.getElementById('get_input');
    const myDiv = document.getElementById('send_input');

    if (!myTextarea || !myDiv) return;

    // Disable send button when input is empty
    const checkInput = () => {
        if (!myTextarea.value.trim()) {
            myDiv.style.pointerEvents = 'none';
            myDiv.style.color = '#0000005c';
            myDiv.style.backgroundColor = '#0000001e'
            myDiv.style.opacity = '0.5';
        } else {
            myDiv.style.pointerEvents = 'auto';
            myDiv.style.color = '#ffffff';
            myDiv.style.backgroundColor = '#e75913af'
            myDiv.style.opacity = '1';
        }

        // Auto-resize textarea to fit content
        myTextarea.style.height = '24px';

        let newHeight = myTextarea.scrollHeight;
        myTextarea.style.height = newHeight + 'px';

        marked.parse(myTextarea.value)
    };

    checkInput();
    myTextarea.addEventListener('input', checkInput);
}


// ── Fetch current user info & quota ─────────────────────────────────

async function fetchUserInfo() {
    try {
        const res = await fetch("/api/user");
        if (!res.ok) {
            if (res.status === 401 || res.status === 302) {
                window.location.href = "/login";
                return;
            }
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();

        if (data.error) {
            console.error("[USER] Error:", data.error);
            return;
        }

        currentUser = data.user;
        currentQuota = data.quota;

        // Update the global user ID for chat requests
        window.CURRENT_USER_ID = currentUser.id;

        updateUserUI();
        updateQuotaUI();
        updateFeatureGating();

    } catch (e) {
        console.error("[USER] Failed to fetch user info:", e);
    }
}

function updateUserUI() {
    if (!currentUser) return;

    const planLabel = document.getElementById("user-menu-plan");
    if (planLabel) {
        const planNames = { free: "Free plan", basic: "Basic plan", plus: "Plus plan" };
        planLabel.textContent = planNames[currentUser.plan] || "Free plan";
    }
}

function updateQuotaUI() {
    if (!currentQuota) return;

    const used = currentQuota.used || 0;
    const limit = currentQuota.limit;
    const isUnlimited = limit === -1;

    // Quota count label
    const quotaCount = document.getElementById("quota-count");
    if (quotaCount) {
        quotaCount.textContent = isUnlimited ? `${used} / ∞` : `${used} / ${limit}`;
    }

    // Quota bar fill
    const quotaBar = document.getElementById("quota-bar-fill");
    if (quotaBar) {
        if (isUnlimited) {
            quotaBar.style.width = "0%";
            quotaBar.style.background = "#3fb299";
        } else {
            const pct = Math.min((used / limit) * 100, 100);
            quotaBar.style.width = pct + "%";
            if (pct >= 90) {
                quotaBar.style.background = "#ef4444";
            } else if (pct >= 70) {
                quotaBar.style.background = "#f59e0b";
            } else {
                quotaBar.style.background = "#3fb299";
            }
        }
    }
}

function updateFeatureGating() {
    if (!currentQuota) return;

    const thinkBtn = document.getElementById("geepthink_funtion_button");
    const searchBtn = document.getElementById("search_funtion_button");

    if (thinkBtn) {
        if (!currentQuota.think_allowed) {
            thinkBtn.classList.add("feature-locked");
            thinkBtn.title = "Upgrade to Basic or Plus to use GeepThink";
        } else {
            thinkBtn.classList.remove("feature-locked");
            thinkBtn.title = "";
        }
    }

    if (searchBtn) {
        if (!currentQuota.search_allowed) {
            searchBtn.classList.add("feature-locked");
            searchBtn.title = "Upgrade to Basic or Plus to use Search";
        } else {
            searchBtn.classList.remove("feature-locked");
            searchBtn.title = "";
        }
    }
}


// ── Error toast system ──────────────────────────────────────────────

function showErrorToast(message, type = "error", duration = 6000) {
    const container = document.getElementById("error-toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `error-toast error-toast-${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <span class="toast-icon">${type === "error" ? "⚠️" : type === "quota" ? "⚡" : ""}</span>
            <span class="toast-message">${marked.parse(message)}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    // Auto-remove
    setTimeout(() => {
        if (toast.parentElement) {
            toast.classList.add("toast-fade-out");
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}


class UIMAN {
    /** Toggle sidebar visibility and layout padding. */
    sideButton() {
        if (document.getElementById('upper_nav').style.visibility === 'visible') {
            document.getElementById('sideBar').style.width = '231px'
            document.getElementById('sideBar').style.padding = '15px 15px 7px 15px'
            document.getElementById('new_chat_text').style.fontSize = '14px'
            document.getElementById('sideBar').style.visibility = 'visible'

            document.getElementById('upper_nav').style.visibility = 'hidden'

            document.getElementById('conversation_con').style.padding = "0 12vw"
            console.log(event.target);

        } else {
            document.getElementById('sideBar').style.width = '0px'
            document.getElementById('sideBar').style.padding = '0px'
            document.getElementById('sideBar').style.visibility = 'hidden'


            document.getElementById('conversation_con').style.padding = "0 22vw"


            document.getElementById('upper_nav').innerHTML = `${document.getElementById('upper_buttons').innerHTML}`

            document.getElementById('upper_nav').style.visibility = 'visible'

            console.log(event.target);

        }

    }

    /** Start a new chat and reset the URL. */
    new_chat_button() {
        active_session = ""
        window.history.pushState({}, "", `/chat/new`);


        let conversation_container = document.getElementById('conversation_con')
        conversation_container.innerHTML = `<div id="new_chat_comment"><p>Ask anything!</p></div>`
        console.log(active_session);

    }


    /** Toggle extended reasoning (GeepThink) mode. */
    think_toggle() {
        // Block if feature is locked
        if (currentQuota && !currentQuota.think_allowed) {
            showErrorToast(
                "**GeepThink** is available on Basic and Plus plans. [Upgrade now](/pricing).",
                "locked"
            );
            return;
        }

        if (think == false) {
            think = true
        } else { think = false }

        let think_button = document.getElementById('geepthink_funtion_button')
        if (think) {
            think_button.style.border = "1px solid #000000"
            think_button.style.color = "#000000"
        } else {
            think_button.style.border = ""
            think_button.style.color = ""

        }
        console.log("think:", think);
    }


    /** Toggle web search mode. */
    search_toggle() {
        // Block if feature is locked
        if (currentQuota && !currentQuota.search_allowed) {
            showErrorToast(
                "**Search** is available on Basic and Plus plans. [Upgrade now](/pricing).",
                "locked"
            );
            return;
        }

        if (search == false) {
            search = true
        } else { search = false }

        let search_button = document.getElementById('search_funtion_button')
        if (search) {
            search_button.style.border = "1px solid #000000"
            search_button.style.color = "#000000"

        } else {
            search_button.style.border = ""
            search_button.style.color = ""

        }
        console.log("search", search);
    }

    /** Toggle the user dropdown menu. */
    toggleUserMenu() {
        const menu = document.getElementById("user-menu");
        if (!menu) return;
        menu.classList.toggle("hide-element");
    }

    /** Show upgrade modal with custom message. */
    showUpgradeModal(title, message) {
        const modal = document.getElementById("upgrade-modal");
        const modalTitle = document.getElementById("upgrade-modal-title");
        const modalMsg = document.getElementById("upgrade-modal-message");

        if (modalTitle) modalTitle.textContent = title || "Upgrade your plan";
        if (modalMsg) modalMsg.innerHTML = message || "Upgrade to continue chatting.";
        if (modal) modal.classList.remove("hide-element");
    }

    /** Close upgrade modal. */
    closeUpgradeModal() {
        const modal = document.getElementById("upgrade-modal");
        if (modal) modal.classList.add("hide-element");
    }

    setting_man_manu() {
        settings_button = document.getElementById('setting-toggle')
    }

}

uiman = new UIMAN()

// Close user menu when clicking outside
document.addEventListener("click", (e) => {
    const menu = document.getElementById("user-menu");
    const profile = document.getElementById("user-profile-section");
    if (menu && profile && !menu.contains(e.target) && !profile.contains(e.target)) {
        menu.classList.add("hide-element");
    }
});


class SessionMan {
    /** Fetch all sessions from the API. */
    async load_all_sessions_pairs() {
        const res = await fetch("/api/sessions");
        this.sessionPairs = await res.json();
        return this.sessionPairs;
    }

    /** Render session names in the sidebar, newest first. */
    list_sessions_in_cat() {
        console.log(this.sessionPairs);
        if (!this.sessionPairs || typeof this.sessionPairs !== 'object') return;
        const cat_element = document.getElementById('cat');
        cat_element.innerHTML = ""

        // Sort by most recently updated
        const sorted = Object.entries(this.sessionPairs).sort((a, b) => {
            return new Date(b[1].date_last_commit) - new Date(a[1].date_last_commit);
        });

        for (const [id, info] of sorted) {
            cat_element.innerHTML += `<div title="${info.session_name}" class="session_name" id="${id}" onclick="conversationMan.load_conversations_in_conversation_con(this)">${info.session_name}</div>`;
        }
    }

}


let get_all_sessions_pairs = () => {
    sessionMan = new SessionMan()
    return sessionMan.load_all_sessions_pairs().then(() => {
        sessionMan.list_sessions_in_cat();
    })

}


let log = () => {
    console.log("click");

}

class ConversationMan {
    constructor() {
        this.conversation_of_active_session = undefined
    }

    async load_conversations() {
        const res = await fetch(`/api/load_conversation_on_session_id?session_id=${active_session}`)
        if (!res.ok) {
            if (res.status === 403) {
                window.location.href = "/chat/new";
                return {};
            }
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        this.conversation_of_active_session = data.conversation
        return this.conversation_of_active_session
    }

    async load_conversations_in_conversation_con(element) {
        active_session = element.id
        window.history.pushState({}, "", `/chat/${active_session}`);

        console.log(active_session);
        let conversation = await this.load_conversations();
        console.log(conversation);
        let conversation_container = document.getElementById('conversation_con')
        conversation_container.innerHTML = ""
        let messages = conversation[active_session]

        for (let i = 0; i < messages.length; i++) {
            const now = Date.now();

            if (messages[i]['role'] === "assistant") {
                conversation_container.innerHTML += `<div class='user' id=${conversation[active_session][i - 1]['id']}>${marked.parse(messages[i - 1]['content'])}</div>`

                let model_id = conversation[active_session][i]['id'],
                    model_source = conversation[active_session][i]['source'],
                    model_thought = conversation[active_session][i]['thought'],
                    model_content = conversation[active_session][i]['content'];

                let parsed_sources = [];
                try { parsed_sources = JSON.parse(model_source); } catch (e) { }

                conversation_container.innerHTML += `
                    <div class="model" id=${model_id}>
                    </div>
                    `

                if (parsed_sources.length > 0) {

                    console.log(parsed_sources);


                    document.getElementById(model_id).innerHTML += `
                        <div class="search-container" id="search-con-${now}">
                            <details class="search" id="search-details-${now}">
                                <summary id="search-summary-${now}">Source</summary>
                                <div class="search-content" id="search-content-${now}"></div>
                            </details>
                        </div>
                    `

                    parsed_sources.forEach(element => {
                        let source_domain = element.sources.url;
                        if (source_domain) {
                            // Matches http(s):// and/or www. and captures everything up to the next slash
                            const match = source_domain.match(/^(?:https?:\/\/)?(?:www\.)?([^\/\?#]+)/i);
                            source_domain = (match && match[1]) ? match[1] : source_domain;
                        }


                        document.getElementById(`search-content-${now}`).innerHTML += `
                        <a href="${element.sources.url}" title="${element.sources.title}"><p>${source_domain}: ${element.sources.title}</p></a>
                        `
                    });
                }

                if (model_thought) {
                    document.getElementById(model_id).innerHTML += `
                        <div class="thought-container" id="thought-con-${now}">
                            <details class="thoughts" id="thoughts-details-${now}">
                                <summary id="thoughts-summary-${now}">Thought</summary>
                                <div class="thought-content" id="thoughts-content-${now}">${marked.parse(model_thought)}</div>
                            </details>
                        </div>
                    `
                }

                if (model_content) {
                    document.getElementById(model_id).innerHTML += `
                        <div class="response" id="response-${now}">${marked.parse(model_content)}</div>
                    `
                    document.getElementById(`response-${now}`).querySelectorAll('pre code').forEach(hljs.highlightElement);
                }
            }



        }

        conversation_container.scrollTop = conversation_container.scrollHeight;


    }


}

conversationMan = new ConversationMan()


class SendMan {

    /** Send a message and stream the assistant response via SSE. */
    async chat() {


        const now = Date.now();
        const input = document.getElementById('get_input');
        const userInput = input.value.trim();
        if (!userInput) return;

        // Pre-flight quota check on the client side
        if (currentQuota && !currentQuota.allowed) {
            uiman.showUpgradeModal(
                "Daily limit reached",
                `You've used all ${currentQuota.limit} messages for today on the <strong>${currentQuota.plan}</strong> plan.`
            );
            return;
        }

        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                "session_id": active_session,
                "user_input": userInput,
                "think": think,
                "search": search,
            }),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();




        const conversation_container = document.getElementById("conversation_con");

        if (!active_session) {
            conversation_container.innerHTML = ""
        }

        let buffer = ""; // SSE frames may split across chunks

        let fullContent = "";
        let fullThought = "";
        let thoughtsClosed = false;

        conversation_container.innerHTML += `<div class='user'>${userInput}</div>`;
        input.value = "";


        conversation_container.innerHTML += `
                    <div class="model">
                        <div class="search-container hide-element" id="search-con-${now}">
                            <details class="search" id="search-details-${now}">
                                <summary id="search-summary-${now}"></summary>
                                <div class="search-content" id="search-content-${now}">
                                </div>
                            </details>
                        </div>
    
                        <div class="thought-container  hide-element" id="thought-con-${now}">
                            <details class="thoughts" id="thoughts-details-${now}">
                                <summary id="thoughts-summary-${now}"></summary>
                                <div class="thought-content" id="thoughts-content-${now}">
                                </div>
                            </details>
                        </div>
    
                        <div class="response" id="response-${now}"></div>
                    </div>
            `
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split("\n\n");
            buffer = parts.pop();

            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith("data: ")) continue;



                try {
                    const payload = JSON.parse(line.slice(6));
                    conversation_container.scrollTop = conversation_container.scrollHeight;

                    // ── Handle server errors (quota, feature lock) ──
                    if (payload.error) {
                        const errorType = payload.error_type || "error";

                        if (errorType === "quota_exceeded") {
                            uiman.showUpgradeModal(
                                "Daily limit reached",
                                marked.parse(payload.error)
                            );
                        } else if (errorType === "feature_locked") {
                            showErrorToast(payload.error, "locked");
                        } else {
                            showErrorToast(payload.error, "error");
                        }

                        // Update local quota state
                        if (payload.quota) {
                            currentQuota = { ...currentQuota, ...payload.quota };
                            updateQuotaUI();
                        }

                        // Remove the empty model response placeholder
                        const responseDiv = document.getElementById(`response-${now}`);
                        if (responseDiv && responseDiv.parentElement) {
                            responseDiv.parentElement.remove();
                        }
                        continue;
                    }

                    // ── Handle quota updates after successful response ──
                    if (payload.quota_update) {
                        currentQuota = { ...currentQuota, ...payload.quota_update };
                        updateQuotaUI();
                        updateFeatureGating();
                        continue;
                    }

                    // console.log("payload keys:", Object.keys(payload)); // ✅ add this
                    if (payload.check_session) {
                        console.log("check_session value:", JSON.stringify(payload.check_session));
                        if (payload.check_session.new_session) {
                            let cat = document.getElementById('cat')
                            let new_session_name = payload.check_session.new_session.session_name
                            let new_session_id = payload.check_session.new_session.session_id

                            active_session = new_session_id
                            window.history.pushState({}, "", `/chat/${new_session_id}`);

                            let new_chat = `<div title="${new_session_name}" class="session_name" id="${new_session_id}" onclick="conversationMan.load_conversations_in_conversation_con(this)">${new_session_name}</div>`

                            cat.insertAdjacentHTML('afterbegin', new_chat)
                        }
                        console.log("check: ", payload.check_session);

                    }


                    if (payload.reasoning_chunk) {
                        const thoughtCon = document.getElementById(`thought-con-${now}`)
                        thoughtCon.classList.remove('hide-element');

                        const summary = document.getElementById(`thoughts-summary-${now}`)
                        if (summary) {
                            summary.innerText = "Thinking"
                            summary.classList.add('status-indicator')
                        }


                        const details = document.getElementById(`thoughts-details-${now}`)
                        if (details) details.open = true;

                        fullThought += payload.reasoning_chunk;
                        const thoughtContent = document.getElementById(`thoughts-content-${now}`)
                        if (thoughtContent) thoughtContent.innerHTML = marked.parse(fullThought);
                        thoughtContent.querySelectorAll('pre code').forEach(hljs.highlightElement);
                    }

                    if (payload.searching) {
                        const element1 = document.querySelector(`#search-con-${now}`);
                        if (element1) element1.classList.remove('hide-element');

                        const summary = document.getElementById(`search-summary-${now}`)

                        if (summary) {
                            summary.innerText = "Searching"
                            summary.classList.add('status-indicator');
                        }
                    }

                    if (payload.sources) {
                        console.log("source: ", payload.sources.url);

                        // Display hostname as link label
                        let source_domain = payload.sources.url;
                        if (source_domain) {
                            const match = source_domain.match(/^(?:https?:\/\/)?(?:www\.)?([^\/\?#]+)/i);
                            source_domain = (match && match[1]) ? match[1] : source_domain;
                        }

                        const summary = document.getElementById(`search-summary-${now}`)
                        if (summary) {
                            summary.innerText = "Sources"
                            summary.classList.remove('status-indicator');
                        }

                        const searchContent = document.getElementById(`search-content-${now}`)

                        searchContent.innerHTML += `<p><a href="${payload.sources.url}" title="${payload.sources.title}">${source_domain}</a></p>`
                    }


                    if (payload.content_chunk) {
                        const summary = document.getElementById(`thoughts-summary-${now}`)
                        if (summary) {

                            summary.innerText = "Thoughts"
                            summary.classList.remove('status-indicator');
                        }


                        const details = document.getElementById(`thoughts-details-${now}`)
                        if (details) {

                            if (details.open == true) {
                                details.open = false;
                            }
                        }


                        fullContent += payload.content_chunk;
                        const responseDiv = document.getElementById(`response-${now}`)
                        if (responseDiv) responseDiv.innerHTML = marked.parse(fullContent);
                        responseDiv.querySelectorAll('pre code').forEach(hljs.highlightElement);
                    }

                    if (payload.search_not_required) {
                        document.getElementById(`search-con-${now}`).remove()
                    }
                } catch (e) {
                    console.warn("Failed to parse SSE payload:", line, e);
                }
            }
        }
    }
}

const sendMan = new SendMan();

document.addEventListener("DOMContentLoaded", async () => {
    // Fetch user info first (populates quota + feature gates)
    await fetchUserInfo();
    await get_all_sessions_pairs();

    if (SESSION_ID_FROM_URL && SESSION_ID_FROM_URL !== "None" && SESSION_ID_FROM_URL !== "new") {
        active_session = SESSION_ID_FROM_URL;
        await conversationMan.load_conversations_in_conversation_con({ id: active_session });
    } else {
        document.getElementById("conversation_con").innerHTML = `<div id="new_chat_comment"><p>Ask anything!</p></div>`;
    }
});

window.addEventListener("popstate", async () => {
    const path = window.location.pathname;
    const session_id = path.split("/chat/")[1];

    if (session_id && session_id !== "new") {
        active_session = session_id;
        await conversationMan.load_conversations_in_conversation_con({ id: active_session });
    } else {
        active_session = "";
        document.getElementById("conversation_con").innerHTML = `<div id="new_chat_comment"><p>Ask anything!</p></div>`;
    }
});