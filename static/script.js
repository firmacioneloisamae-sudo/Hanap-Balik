"use strict";

var $ = function (selector) {
    return document.querySelector(selector);
};

var ICONS = {
    box: '<svg class="i"><use href="#box"/></svg>',
    pin: '<svg class="i"><use href="#pin"/></svg>',
    cal: '<svg class="i"><use href="#cal"/></svg>',
    search: '<svg class="i"><use href="#search"/></svg>',
    plus: '<svg class="i"><use href="#plus"/></svg>',
    shield: '<svg class="i"><use href="#shield"/></svg>',
    out: '<svg class="i"><use href="#out"/></svg>',
    cog: '<svg class="i"><use href="#cog"/></svg>',
    file: '<svg class="i"><use href="#file"/></svg>',
    grid: '<svg class="i"><use href="#grid"/></svg>'
};

var TITLES = {
    dashboard: ["Your dashboard", "Here’s what’s happening with your reports."],
    report: ["Report an item", "Share clear details so the right person can recognize it."],
    search: ["Search items", "Filter by keyword, status, category or date."],
    reports: ["My reports", "Update or remove your open reports."],
    matches: ["Possible matches", "Items with a similar name and category."],
    claims: ["My claims", "Follow the review status of your ownership claims."],
    settings: ["Account settings", "Update your account details and password."],
    admin: ["Administrator dashboard", "Review claims, reports and account verification."]
};

var currentUser = null;
var csrfToken = document.querySelector('meta[name="csrf-token"]').content;
var pendingClaimItem = null;
var adminClaims = [];
var toastTimer = null;

async function api(path, options) {
    options = options || {};
    var headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body instanceof FormData) {
        headers.set("X-CSRF-Token", csrfToken);
    } else if (options.body !== undefined) {
        headers.set("Content-Type", "application/json");
        headers.set("X-CSRF-Token", csrfToken);
    } else if (["POST", "PUT", "PATCH", "DELETE"].includes(options.method)) {
        headers.set("X-CSRF-Token", csrfToken);
    }

    var response = await fetch(path, Object.assign({
        credentials: "same-origin"
    }, options, { headers: headers }));
    var result = {};
    if ((response.headers.get("content-type") || "").includes("application/json")) {
        result = await response.json();
    }
    if (!response.ok) {
        throw new Error(result.error || "The request could not be completed.");
    }
    if (result.csrf_token) {
        csrfToken = result.csrf_token;
        document.querySelector('meta[name="csrf-token"]').content = csrfToken;
    }
    return result;
}

function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
        return {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        }[char];
    });
}

function formatDate(value) {
    if (!value) return "Date not set";
    return new Date(value + "T00:00:00").toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric"
    });
}

function badgeClass(status) {
    return {
        Lost: "b-lost",
        Found: "b-found",
        Open: "b-pend",
        Pending: "b-pend",
        Matched: "b-match",
        Approved: "b-ret",
        Returned: "b-ret",
        Rejected: "b-lost"
    }[status] || "b-pend";
}

function toast(message) {
    var element = $("#toast");
    element.textContent = message;
    element.classList.add("on");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
        element.classList.remove("on");
    }, 3200);
}

function setLoading(button, loading, text) {
    if (!button) return;
    if (loading) {
        button.dataset.originalText = button.textContent;
        button.textContent = text || "Working…";
        button.disabled = true;
    } else {
        button.textContent = button.dataset.originalText || button.textContent;
        button.disabled = false;
        delete button.dataset.originalText;
    }
}

function showError(fieldId, message) {
    var field = $("#" + fieldId);
    var error = field && field.parentElement.querySelector(".er");
    if (field) field.classList.add("err");
    if (error) {
        error.textContent = message;
        error.classList.add("on");
    } else {
        toast(message);
    }
}

function clearErrors(form) {
    form.querySelectorAll(".er").forEach(function (element) {
        element.classList.remove("on");
    });
    form.querySelectorAll(".err").forEach(function (element) {
        element.classList.remove("err");
    });
}

function itemCard(item, manageable) {
    var photo = item.photo_url
        ? '<img src="' + escapeHtml(item.photo_url) + '" alt="" style="width:100%;height:130px;object-fit:cover;border-radius:10px;margin-bottom:14px">'
        : '<div class="thumb">' + ICONS.box + "</div>";
    var ownerDetails = item.identifying_details
        ? '<p class="sm"><b>Private details:</b> ' +
            escapeHtml(item.identifying_details) + "</p>"
        : "";
    var controls = "";
    if (manageable) {
        controls = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
            (item.status === "Open"
                ? '<button class="btn out" type="button" data-action="edit-item" data-id="' +
                    item.id + '">Edit</button>'
                : "") +
            '<button class="btn dng" type="button" data-action="delete-item" data-id="' +
            item.id + '">Delete</button></div>';
    } else if (item.report_type === "Found" && item.status === "Open") {
        controls = '<a class="btn pri" style="width:100%;margin-top:12px" ' +
            'href="#claims" data-claim-item="' + item.id + '">Submit a claim</a>';
    }
    return '<article class="card item-card" data-item-id="' + item.id + '">' +
        photo +
        '<div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">' +
        "<h3>" + escapeHtml(item.title) + "</h3>" +
        '<span class="badge ' + badgeClass(item.report_type) + '">' +
        escapeHtml(item.report_type) + "</span></div>" +
        '<div class="meta"><span>' + ICONS.pin + escapeHtml(item.location) +
        "</span><span>" + ICONS.cal + escapeHtml(formatDate(item.event_date)) +
        '</span><span class="badge ' + badgeClass(item.status) + '">' +
        escapeHtml(item.status) + "</span></div>" +
        '<p class="sm mu">' + escapeHtml(item.category) + "</p>" +
        '<details><summary class="sm" style="cursor:pointer;color:var(--teal);font-weight:600">View details</summary>' +
        '<p class="sm">' + escapeHtml(item.description) + "</p>" +
        ownerDetails + "</details>" + controls + "</article>";
}

function renderItems(container, records, emptyMessage, manageable) {
    if (!container) return;
    container.innerHTML = records.length
        ? records.map(function (item) {
            return itemCard(item, manageable);
        }).join("")
        : '<div class="card empty" style="grid-column:1/-1">' +
            '<b style="color:var(--tx)">' + escapeHtml(emptyMessage) + "</b></div>";
}

function renderNav(page) {
    var nav = $("#nav");
    if (!currentUser) {
        nav.innerHTML = '<a class="logo" href="#home"><span class="mark">' +
            ICONS.search + "</span>HanapBalik</a>" +
            '<a href="#search" class="' + (page === "search" ? "on" : "") + '">' +
            ICONS.search + "Browse items</a><span class=\"gap\"></span>" +
            '<a href="#login">Log in</a><a href="#signup">Sign up</a>';
        return;
    }
    var links = [
        ["dashboard", ICONS.grid, "Dashboard"],
        ["report", ICONS.plus, "Report lost or found"],
        ["search", ICONS.search, "Browse items"],
        ["reports", ICONS.file, "My reports"],
        ["matches", ICONS.search, "Possible matches"],
        ["claims", ICONS.shield, "My claims"],
        ["settings", ICONS.cog, "Account settings"]
    ];
    if (currentUser.is_admin) {
        links.push(["admin", ICONS.grid, "Admin dashboard"]);
    }
    nav.innerHTML = '<a class="logo" href="#home"><span class="mark">' +
        ICONS.search + "</span>HanapBalik</a>" +
        links.map(function (link) {
            var active = link[0] === page ? " on" : "";
            return '<a href="#' + link[0] + '" class="' + active + '">' +
                link[1] + escapeHtml(link[2]) + "</a>";
        }).join("") +
        '<span class="gap"></span><button class="btn out" id="theme-toggle" type="button" style="margin-top:8px">Toggle theme</button>' +
        '<button class="btn out" id="logout" type="button" style="margin-top:8px">' +
        ICONS.out + "Log out</button>";
    nav.classList.remove("open");
}

function setUser(user) {
    currentUser = user;
    document.querySelectorAll(".links").forEach(function (links) {
        if (user) {
            links.innerHTML = '<a href="#dashboard">Dashboard</a>' +
                '<a class="btn pri" style="padding:8px 16px;min-height:38px;color:#fff" href="#report">Report an item</a>';
        } else {
            links.innerHTML = '<a href="#login">Log in</a>' +
                '<a class="btn pri" style="padding:8px 16px;min-height:38px;color:#fff" href="#signup">Sign up</a>';
        }
    });
}

function go(page, section) {
    if (section) {
        location.hash = page;
        window.setTimeout(function () {
            var target = document.getElementById(section);
            if (target) target.scrollIntoView();
        }, 0);
        return;
    }
    location.hash = page;
}

async function loadRecentItems() {
    var result = await api("/api/items");
    renderItems(document.querySelector(".items:not(#sr)"), result.items.slice(0, 3),
        "No items have been reported yet.");
}

async function loadSearch() {
    var params = new URLSearchParams();
    if ($("#kw").value.trim()) params.set("q", $("#kw").value.trim());
    if ($("#fs").value) params.set("type", $("#fs").value);
    if ($("#fc").value) params.set("category", $("#fc").value);
    if ($("#fd").value) params.set("date", $("#fd").value);
    var result = await api("/api/items?" + params.toString());
    renderItems($("#sr"), result.items, "No items match your search.");
}

async function loadDashboard() {
    var result = await api("/api/dashboard");
    Object.keys(result.stats).forEach(function (key) {
        var element = $("#ds-" + key);
        if (element) element.textContent = result.stats[key];
    });
    var body = $("#dashboard-reports");
    body.innerHTML = result.reports.length
        ? result.reports.map(function (item) {
            return "<tr><td>" + escapeHtml(item.title) + "</td><td>" +
                '<span class="badge ' + badgeClass(item.report_type) + '">' +
                escapeHtml(item.report_type) + "</span></td><td>" +
                '<span class="badge ' + badgeClass(item.status) + '">' +
                escapeHtml(item.status) + "</span></td><td>" +
                (item.status === "Matched" ? "Matched" : "None yet") + "</td><td>" +
                escapeHtml(formatDate(item.event_date)) + "</td></tr>";
        }).join("")
        : '<tr><td colspan="5" class="empty">You have not submitted any reports.</td></tr>';
    $("#dashboard-activity").textContent = result.stats.claims
        ? result.stats.claims + " claim(s) are waiting for review."
        : result.reports.length
            ? "Your recent reports are up to date."
            : "Your reports and claim updates will appear here.";
}

async function loadMyReports() {
    var result = await api("/api/items?mine=1");
    renderItems($("#my-reports"), result.items, "You have not submitted any reports.", true);
}

async function loadMatches() {
    var result = await api("/api/matches");
    renderItems($("#possible-matches"), result.items,
        "No possible matches found yet. Check back when new items are reported.");
}

async function loadClaims() {
    var found = await api("/api/items?type=Found&exclude_mine=1");
    var available = found.items.filter(function (item) {
        return item.status === "Open";
    });
    var select = $("#claim-item");
    select.innerHTML = available.length
        ? '<option value="">Choose a found item</option>' + available.map(function (item) {
            return '<option value="' + item.id + '">' + escapeHtml(item.title) +
                " — " + escapeHtml(item.location) + " (" +
                escapeHtml(formatDate(item.event_date)) + ")</option>";
        }).join("")
        : '<option value="">No available found items</option>';
    if (pendingClaimItem && available.some(function (item) {
        return item.id === pendingClaimItem;
    })) {
        select.value = String(pendingClaimItem);
        pendingClaimItem = null;
    }
    var result = await api("/api/claims");
    $("#claim-list").innerHTML = result.claims.length
        ? result.claims.map(function (claim) {
            return '<div class="act"><span class="dot">' + ICONS.shield +
                '</span><div><b>' + escapeHtml(claim.item_title) + "</b>" +
                '<div class="sm mu">' + escapeHtml(claim.item_location) +
                " · " + escapeHtml(formatDate(claim.item_date)) + "</div>" +
                '<span class="badge ' + badgeClass(claim.status) + '">' +
                escapeHtml(claim.status) + "</span></div></div>";
        }).join("")
        : '<div class="empty">You have not submitted any claims yet.</div>';
}

async function loadSettings() {
    var result = await api("/api/me");
    $("#account-name").value = result.user.full_name;
    $("#account-email").value = result.user.email;
    $("#account-contact").value = currentUser.contact_number || "";
}

async function loadAdmin() {
    var values = await Promise.all([
        api("/api/admin/summary"),
        api("/api/claims?all=1"),
        api("/api/admin/items"),
        api("/api/admin/users")
    ]);
    var stats = values[0].stats;
    $("#as-items").textContent = stats.items;
    $("#as-users").textContent = stats.users;
    $("#as-claims").textContent = stats.claims;
    $("#as-matched").textContent = stats.matched;
    $("#as-returned").textContent = stats.returned;
    adminClaims = values[1].claims;
    renderAdminClaims();
    $("#admin-items").innerHTML = values[2].items.length
        ? values[2].items.map(function (item) {
            return "<tr><td>" + escapeHtml(item.title) + "</td><td>" +
                escapeHtml(item.report_type) + "</td><td>" +
                escapeHtml(item.reporter) + "</td><td>" +
                '<span class="badge ' + badgeClass(item.status) + '">' +
                escapeHtml(item.status) + "</span></td><td>" +
                (item.status !== "Returned"
                    ? '<button class="btn out" type="button" data-action="return-item" data-id="' +
                        item.id + '">Mark returned</button>'
                    : "Closed") + "</td></tr>";
        }).join("")
        : '<tr><td colspan="5" class="empty">No reports yet.</td></tr>';
    $("#admin-users").innerHTML = values[3].users.map(function (user) {
        return "<tr><td>" + escapeHtml(user.full_name) + "</td><td>" +
            escapeHtml(user.email) + "</td><td>" +
            (user.is_verified ? "Verified" : "Pending") + "</td><td>" +
            '<button class="btn out" type="button" data-action="verify-user" data-id="' +
            user.id + '" data-verified="' + user.is_verified + '">' +
            (user.is_verified ? "Revoke verification" : "Verify") + "</button> " +
            (user.has_id_document
                ? '<button class="btn out" type="button" data-action="identity" data-id="' +
                    user.id + '">Review ID</button>'
                : "") + "</td></tr>";
    }).join("") || '<tr><td colspan="4" class="empty">No accounts yet.</td></tr>';
}

function renderAdminClaims() {
    var query = $("#aq").value.trim().toLowerCase();
    var status = $("#claim-status-filter").value;
    var filtered = adminClaims.filter(function (claim) {
        return (!status || claim.status === status) &&
            (!query || [
                claim.id,
                claim.item_title,
                claim.claimant_name,
                claim.claimant_email
            ].join(" ").toLowerCase().includes(query));
    });
    $("#at").innerHTML = filtered.length
        ? filtered.map(function (claim) {
            var action = "";
            if (claim.status === "Pending") {
                action = '<button class="btn out" type="button" data-action="review-claim" data-status="Approved" data-id="' +
                    claim.id + '">Approve</button> <button class="btn dng" type="button" data-action="review-claim" data-status="Rejected" data-id="' +
                    claim.id + '">Reject</button>';
            } else if (claim.status === "Approved") {
                action = '<button class="btn out" type="button" data-action="review-claim" data-status="Returned" data-id="' +
                    claim.id + '">Mark returned</button>';
            } else {
                action = '<span class="sm mu">Reviewed</span>';
            }
            var evidence = '<details><summary style="cursor:pointer">View evidence</summary><p class="sm">' +
                escapeHtml(claim.evidence) + "</p>";
            if (claim.evidence_file_url) {
                evidence += '<a class="btn out" href="' +
                    escapeHtml(claim.evidence_file_url) + '">Evidence</a>';
            }
            evidence += "</details>";
            return "<tr><td>C-" + claim.id + "</td><td>" +
                escapeHtml(claim.item_title) + "</td><td>" +
                escapeHtml(claim.claimant_name) + "</td><td>" +
                '<span class="badge ' + badgeClass(claim.status) + '">' +
                escapeHtml(claim.status) + "</span></td><td>" + evidence +
                "</td><td>" + action + "</td></tr>";
        }).join("")
        : '<tr><td colspan="6" class="empty">No claims match.</td></tr>';
}

async function route() {
    var hash = (location.hash || "#home").slice(1);
    if (["how", "safety", "about"].includes(hash)) {
        var section = hash;
        document.querySelectorAll(".page").forEach(function (page) {
            page.classList.remove("on");
        });
        $("#p-home").classList.add("on");
        window.setTimeout(function () {
            var target = document.getElementById(section);
            if (target) target.scrollIntoView();
        }, 0);
        return;
    }
    if (!Object.prototype.hasOwnProperty.call(TITLES, hash) &&
        !["home", "login", "signup"].includes(hash)) {
        hash = "home";
    }
    if (TITLES[hash] && !currentUser && hash !== "search") {
        toast("Please log in to continue.");
        location.hash = "login";
        return;
    }
    if (hash === "admin" && (!currentUser || !currentUser.is_admin)) {
        toast("Administrator access is required.");
        location.hash = "dashboard";
        return;
    }
    document.querySelectorAll(".page").forEach(function (page) {
        page.classList.remove("on");
    });
    if (TITLES[hash]) {
        $("#p-app").classList.add("on");
        document.querySelectorAll(".v").forEach(function (view) {
            view.style.display = "none";
        });
        $("#v-" + hash).style.display = "block";
        $("#ttl").textContent = TITLES[hash][0];
        $("#sub").textContent = TITLES[hash][1];
        $("#qa").innerHTML = hash === "dashboard"
            ? '<a class="btn acc" href="#report">' + ICONS.plus + "Report item</a>"
            : "";
        renderNav(hash);
    } else {
        $("#p-" + hash).classList.add("on");
    }
    window.scrollTo(0, 0);
    try {
        if (hash === "home") await loadRecentItems();
        if (hash === "dashboard") await loadDashboard();
        if (hash === "search") await loadSearch();
        if (hash === "reports") await loadMyReports();
        if (hash === "matches") await loadMatches();
        if (hash === "claims") await loadClaims();
        if (hash === "settings") await loadSettings();
        if (hash === "admin") await loadAdmin();
    } catch (error) {
        toast(error.message);
    }
}

function confirmAction(title, message, action) {
    var dialog = $("#dg");
    $("#dt").textContent = title;
    $("#dp").textContent = message;
    $("#dok").onclick = function () {
        dialog.close();
        action();
    };
    dialog.showModal();
}

async function withButton(button, message, action) {
    setLoading(button, true);
    try {
        await action();
    } catch (error) {
        toast(error.message || message);
    } finally {
        setLoading(button, false);
    }
}

function initForms() {
    $("#lf").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        clearErrors(form);
        var email = $("#le").value.trim();
        var password = $("#lp").value;
        var valid = true;
        if (!/^\S+@\S+\.\S+$/.test(email)) {
            showError("le", "Enter a valid email address.");
            valid = false;
        }
        if (password.length < 8) {
            showError("lp", "Password must be at least 8 characters.");
            valid = false;
        }
        if (!valid) return;
        var button = $("#lb");
        await withButton(button, "Log in failed.", async function () {
            var result = await api("/api/auth/login", {
                method: "POST",
                body: JSON.stringify({
                    email: email,
                    password: password,
                    remember: form.querySelector('input[type="checkbox"]').checked
                })
            });
            setUser(result.user);
            toast("Welcome back.");
            go("dashboard");
        });
    });

    $("#sf").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        clearErrors(form);
        var valid = true;
        var email = $("#se").value.trim();
        var contact = $("#sc").value.trim();
        var password = $("#sp").value;
        if ($("#sn").value.trim().length < 2) {
            showError("sn", "Enter your full name.");
            valid = false;
        }
        if (contact.replace(/\D/g, "").length < 10) {
            showError("sc", "Enter a valid contact number.");
            valid = false;
        }
        if (!/^\S+@\S+\.\S+$/.test(email)) {
            showError("se", "Enter a valid email address.");
            valid = false;
        }
        if (password.length < 8) {
            showError("sp", "Use at least 8 characters.");
            valid = false;
        }
        if (!password || password !== $("#sq").value) {
            showError("sq", "Passwords do not match.");
            valid = false;
        }
        if (!$("#si").value.trim()) {
            showError("si", "Enter your ID number.");
            valid = false;
        }
        if (!$("#sf1").files.length) {
            toast("Upload a valid ID image or PDF.");
            valid = false;
        }
        if (!$("#sa").checked) {
            toast("Please accept the Terms to continue.");
            valid = false;
        }
        if (!valid) return;
        var payload = new FormData();
        payload.set("full_name", $("#sn").value.trim());
        payload.set("contact_number", contact);
        payload.set("email", email);
        payload.set("password", password);
        payload.set("id_type", $("#st").value);
        payload.set("id_number", $("#si").value.trim());
        payload.set("terms", "true");
        payload.set("id_file", $("#sf1").files[0]);
        await withButton(form.querySelector('button[type="submit"],button:not([type])'),
            "Account creation failed.", async function () {
                var result = await api("/api/auth/signup", {
                    method: "POST",
                    body: payload
                });
                setUser(result.user);
                toast("Account created. Your ID is awaiting administrator verification.");
                go("dashboard");
            });
    });

    $("#rf").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        clearErrors(form);
        var valid = true;
        [["rn", "Give the item a short name."],
            ["rd", "Describe the item so others can recognize it."],
            ["rl", "Add where it happened."],
            ["rdt", "Choose the date it was lost or found."]].forEach(function (entry) {
            if (!$("#" + entry[0]).value.trim()) {
                showError(entry[0], entry[1]);
                valid = false;
            }
        });
        if (!valid) return;
        var payload = new FormData();
        payload.set("report_type", $("#rt").value);
        payload.set("category", $("#rc").value);
        payload.set("title", $("#rn").value.trim());
        payload.set("description", $("#rd").value.trim());
        payload.set("event_date", $("#rdt").value);
        payload.set("location", $("#rl").value.trim());
        payload.set("identifying_details", $("#ri").value.trim());
        if ($("#rp").files[0]) payload.set("photo", $("#rp").files[0]);
        var button = form.querySelector('button[type="submit"],button:not([type])');
        await withButton(button, "Report could not be submitted.", async function () {
            await api("/api/items", { method: "POST", body: payload });
            form.reset();
            $("#report-photo-name").textContent = "Upload a photo";
            toast("Report submitted.");
            go("dashboard");
        });
    });

    $("#claim-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        clearErrors(form);
        if (!$("#claim-item").value) {
            showError("claim-item", "Choose an available found item.");
            return;
        }
        if (!$("#ce").value.trim()) {
            showError("ce", "Add evidence so an administrator can verify your claim.");
            return;
        }
        var payload = new FormData();
        payload.set("item_id", $("#claim-item").value);
        payload.set("evidence", $("#ce").value.trim());
        if ($("#cf").files[0]) payload.set("evidence_file", $("#cf").files[0]);
        await withButton(form.querySelector('button[type="submit"]'),
            "Claim could not be submitted.", async function () {
                await api("/api/claims", { method: "POST", body: payload });
                form.reset();
                $("#claim-file-name").textContent = "Attach a photo or receipt (private)";
                toast("Claim submitted for review.");
                await loadClaims();
            });
    });

    $("#account-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var button = event.currentTarget.querySelector('button[type="submit"]');
        await withButton(button, "Account could not be updated.", async function () {
            var result = await api("/api/account", {
                method: "PUT",
                body: JSON.stringify({
                    full_name: $("#account-name").value.trim(),
                    contact_number: $("#account-contact").value.trim()
                })
            });
            currentUser.full_name = result.user.full_name;
            currentUser.contact_number = $("#account-contact").value.trim();
            toast("Account details saved.");
        });
    });

    $("#password-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        if ($("#new-password").value !== $("#confirm-password").value) {
            toast("The new passwords do not match.");
            return;
        }
        var button = form.querySelector('button[type="submit"]');
        await withButton(button, "Password could not be updated.", async function () {
            await api("/api/account/password", {
                method: "PUT",
                body: JSON.stringify({
                    current_password: $("#current-password").value,
                    new_password: $("#new-password").value
                })
            });
            form.reset();
            toast("Password updated.");
        });
    });
}

function initEvents() {
    window.addEventListener("hashchange", route);
    $("#home-search").addEventListener("submit", function (event) {
        event.preventDefault();
        $("#kw").value = $("#home-keyword").value.trim();
        go("search");
    });
    document.body.addEventListener("click", function (event) {
        var reportLink = event.target.closest("[data-report-type]");
        if (reportLink) $("#rt").value = reportLink.dataset.reportType;
    });
    $("#menu-toggle").addEventListener("click", function () {
        $("#nav").classList.toggle("open");
    });
    $("#nav").addEventListener("click", async function (event) {
        var target = event.target.closest("button");
        if (!target) return;
        if (target.id === "theme-toggle") {
            var root = document.documentElement;
            var next = root.dataset.theme === "dark" ? "light" : "dark";
            root.dataset.theme = next;
            localStorage.setItem("hanapbalik-theme", next);
        }
        if (target.id === "logout") {
            await withButton(target, "Could not log out.", async function () {
                await api("/api/auth/logout", { method: "POST" });
                setUser(null);
                toast("You have been logged out.");
                go("home");
            });
        }
    });
    $("#nav").addEventListener("click", function (event) {
        if (event.target.closest("a")) $("#nav").classList.remove("open");
    });
    $("#sr").addEventListener("click", function (event) {
        var link = event.target.closest("[data-claim-item]");
        if (link) pendingClaimItem = Number(link.dataset.claimItem);
    });
    $("#cf").addEventListener("change", function () {
        $("#claim-file-name").textContent = this.files[0]
            ? this.files[0].name
            : "Attach a photo or receipt (private)";
    });
    $("#sf1").addEventListener("change", function () {
        $("#fn").textContent = this.files[0]
            ? this.files[0].name
            : "Choose a file (JPG, PNG or PDF)";
    });
    $("#rp").addEventListener("change", function () {
        $("#report-photo-name").textContent = this.files[0]
            ? this.files[0].name
            : "Upload a photo";
    });
    document.querySelectorAll(".eye").forEach(function (button) {
        button.addEventListener("click", function () {
            var input = $("#" + button.dataset.input);
            if (input) input.type = input.type === "password" ? "text" : "password";
        });
    });
    ["kw", "fs", "fc", "fd"].forEach(function (id) {
        $("#" + id).addEventListener(id === "kw" ? "input" : "change", function () {
            if (location.hash === "#search") loadSearch().catch(function (error) {
                toast(error.message);
            });
        });
    });
    $("#aq").addEventListener("input", renderAdminClaims);
    $("#claim-status-filter").addEventListener("change", renderAdminClaims);
    $("#at").addEventListener("click", function (event) {
        var button = event.target.closest("[data-action=review-claim]");
        if (!button) return;
        var status = button.dataset.status;
        confirmAction(status + " this claim?",
            "The claim status and item availability will be updated.",
            function () {
                withButton(button, "Claim could not be updated.", async function () {
                    await api("/api/admin/claims/" + button.dataset.id, {
                        method: "PATCH",
                        body: JSON.stringify({ status: status })
                    });
                    toast("Claim " + status.toLowerCase() + ".");
                    await loadAdmin();
                });
            });
    });
    $("#admin-items").addEventListener("click", function (event) {
        var button = event.target.closest("[data-action=return-item]");
        if (!button) return;
        confirmAction("Mark this item returned?",
            "This closes the report and any approved claim.",
            function () {
                withButton(button, "Item status could not be updated.", async function () {
                    await api("/api/items/" + button.dataset.id, {
                        method: "PATCH",
                        body: JSON.stringify({ status: "Returned" })
                    });
                    toast("Item marked returned.");
                    await loadAdmin();
                });
            });
    });
    $("#admin-users").addEventListener("click", function (event) {
        var button = event.target.closest("[data-action=verify-user]");
        if (button) {
            var verified = button.dataset.verified !== "true";
            withButton(button, "Account verification could not be updated.", async function () {
                await api("/api/admin/users/" + button.dataset.id, {
                    method: "PATCH",
                    body: JSON.stringify({ is_verified: verified })
                });
                toast(verified ? "Account verified." : "Verification revoked.");
                await loadAdmin();
            });
            return;
        }
        var identityButton = event.target.closest("[data-action=identity]");
        if (!identityButton) return;
        withButton(identityButton, "Identity details could not be loaded.", async function () {
            var identity = await api("/api/admin/identity/" + identityButton.dataset.id);
            $("#identity-title").textContent = "Identity: " + identity.full_name;
            $("#identity-details").innerHTML =
                "<p><b>Contact:</b> " + escapeHtml(identity.contact_number) + "</p>" +
                "<p><b>ID type:</b> " + escapeHtml(identity.id_type) + "</p>" +
                "<p><b>ID number:</b> " + escapeHtml(identity.id_number) + "</p>";
            var download = $("#identity-download");
            download.hidden = !identity.id_file_url;
            if (identity.id_file_url) download.href = identity.id_file_url;
            $("#identity-dg").showModal();
        });
    });
    document.body.addEventListener("click", function (event) {
        var edit = event.target.closest("[data-action=edit-item]");
        if (edit) openEditDialog(Number(edit.dataset.id));
        var remove = event.target.closest("[data-action=delete-item]");
        if (remove) {
            confirmAction("Delete this report?",
                "This action cannot be undone. Reports with claims cannot be deleted.",
                function () {
                    withButton(remove, "Report could not be deleted.", async function () {
                        await api("/api/items/" + remove.dataset.id, { method: "DELETE" });
                        toast("Report deleted.");
                        await loadMyReports();
                    });
                });
        }
    });
    $("#edit-item-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        var button = form.querySelector('button[type="submit"]');
        await withButton(button, "Report could not be updated.", async function () {
            await api("/api/items/" + $("#edit-item-id").value, {
                method: "PATCH",
                body: JSON.stringify({
                    title: $("#edit-title").value.trim(),
                    category: $("#edit-category").value,
                    report_type: $("#edit-type").value,
                    description: $("#edit-description").value.trim(),
                    event_date: $("#edit-date").value,
                    location: $("#edit-location").value.trim(),
                    identifying_details: $("#edit-identifying").value.trim()
                })
            });
            $("#edit-dg").close();
            toast("Report updated.");
            await loadMyReports();
        });
    });
    $("#close-dialog").addEventListener("click", function () {
        $("#dg").close();
    });
    $("#cancel-edit").addEventListener("click", function () {
        $("#edit-dg").close();
    });
    $("#close-identity").addEventListener("click", function () {
        $("#identity-dg").close();
    });
}

async function openEditDialog(itemId) {
    try {
        var result = await api("/api/items?mine=1");
        var item = result.items.find(function (record) {
            return record.id === itemId;
        });
        if (!item) throw new Error("Report not found.");
        $("#edit-item-id").value = item.id;
        $("#edit-title").value = item.title;
        $("#edit-category").value = item.category;
        $("#edit-type").value = item.report_type;
        $("#edit-description").value = item.description;
        $("#edit-date").value = item.event_date;
        $("#edit-location").value = item.location;
        $("#edit-identifying").value = item.identifying_details || "";
        $("#edit-dg").showModal();
    } catch (error) {
        toast(error.message);
    }
}

async function init() {
    var savedTheme = localStorage.getItem("hanapbalik-theme");
    if (savedTheme === "light" || savedTheme === "dark") {
        document.documentElement.dataset.theme = savedTheme;
    }
    initForms();
    initEvents();
    try {
        var result = await api("/api/me");
        csrfToken = result.csrf_token;
        document.querySelector('meta[name="csrf-token"]').content = csrfToken;
        setUser(result.user);
        await route();
    } catch (error) {
        toast(error.message || "Could not connect to HanapBalik.");
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
