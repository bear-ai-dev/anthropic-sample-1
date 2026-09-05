/**
 * Held-out fixtures. Shapes follow the workspace types; values are the
 * harness's own so that a candidate cannot key off anything it shipped with.
 */

const IMG = "https://cdn.invalid/media";

function storageItem(id: string) {
    return { id, type: "profile", urls: { small: `${IMG}/${id}-small.jpg`, large: `${IMG}/${id}-large.jpg` } };
}

function makeUser(id: string, username: string, displayName: string) {
    return {
        id,
        displayName,
        username,
        bio: "",
        gender: "hide",
        profileImage: storageItem(`${username}-profile`),
        bannerImage: storageItem(`${username}-banner`),
        campus: null,
        birthdate: 0,
        phone: "",
        emails: [],
        socials: {},
        isAdmin: false,
        privacyOptions: {},
        agreements: [],
        verifiedHost: true,
        tapToPayHost: false,
        linkId: `link-${username}`,
        linkUrl: `https://lnk.invalid/${username}`,
        lastReadNotificationDate: 0,
        teamTitle: "",
        lastOnline: 0,
        blocked: [],
        stripeCustomerId: "",
        stripeConnectAccountId: `acct-${username}`,
        stripeConnectStatus: "complete",
        joinIndex: 1,
        dateCreated: 0,
        isFriend: false,
        numFriends: 0,
        numGroups: 0,
        numMutualFriends: 0,
        numProfileViews: 0,
        numAttending: 0,
        numHosting: 0,
        numAttended: 0,
        numHosted: 0,
    };
}

export const USERS = {
    ada: makeUser("user-ada", "ada", "Ada Vance"),
    grace: makeUser("user-grace", "grace", "Grace Ito"),
};

export type UserKey = keyof typeof USERS;

function ticket(id: string, name: string, price: number, order: number) {
    return {
        id,
        name,
        price,
        description: "",
        capacity: 100,
        sold: 0,
        order,
        hide: false,
        settings: {
            approvalRequired: false,
            transferable: false,
            organizationRestrictions: [],
            platformRestriction: null,
            salesDisplayType: "remaining",
            salesVisibility: false,
        },
        groupRestriction: null,
        colors: ["#35D447"],
        hidden: false,
        inPersonOnly: false,
        dateOpen: null,
        dateExpire: null,
        maxPerUser: null,
        disabled: false,
    };
}

export function makeEvent(overrides: Record<string, unknown> = {}) {
    return {
        id: "event-solstice",
        name: "Solstice Rooftop",
        description: "Longest day, highest roof.",
        flyer: {
            id: "flyer-solstice",
            type: "flyer",
            urls: { small: `${IMG}/solstice-small.jpg`, large: `${IMG}/solstice-large.jpg` },
        },
        linkId: "link-solstice",
        publicLink: "",
        videoUrl: null,
        gallery: [
            { id: "gal-server-1", type: "eventGalleryImage", urls: { small: `${IMG}/g1-small.jpg`, large: `${IMG}/g1-large.jpg` } },
            { id: "gal-server-2", type: "eventGalleryImage", urls: { small: `${IMG}/g2-small.jpg`, large: `${IMG}/g2-large.jpg` } },
        ],
        waiver: { url: `${IMG}/waiver.pdf`, signDate: null },
        organizationHostId: "",
        visibility: { showToPublic: true, showToFriends: true, showToCampus: null },
        location: {
            address: {
                line1: "88 Harbour Way",
                line2: "",
                city: "Oakland",
                state: "CA",
                country: "USA",
                zipcode: "94607",
                label: "",
            },
            geoPoint: { latitude: 37.7955, longitude: -122.2793 },
            name: "Harbour Rooftop",
        },
        verified: false,
        color: "#331074",
        effect: "",
        settings: {
            legalAge: false,
            maxTicketsPerUser: 0,
            restrictMultipleRsvpToOrganization: false,
            allowSharing: false,
            chatVisibility: "attendees",
            hideGuestListOption: "never",
            hideGuestListCount: false,
            hostCoversFee: false,
            hideEndDate: false,
            dateReleaseAddress: null,
            requireAge21: false,
            requireValidId: false,
            requireStudentId: false,
        },
        eventType: "sellTickets",
        scrapeMetadata: null,
        musicTrack: null,
        tickets: [ticket("tk-early", "Early Bird", 1500, 0), ticket("tk-door", "At The Door", 2500, 1)],
        questionnaires: [
            { id: "q-diet", question: "Any dietary needs?", description: null, ordering: 0, isRequired: false },
            { id: "q-plus", question: "Bringing a plus one?", description: null, ordering: 1, isRequired: true },
        ],
        dateStart: 1939755600,
        dateEnd: 1939770000,
        organizer: {
            destination: "user/user-ada",
            name: "Ada Vance",
            imageUrl: `${IMG}/ada.jpg`,
            isVerified: false,
        },
        previewUsers: [],
        linkUrl: "https://lnk.invalid/event/solstice",
        invitedPrivilege: null,
        currentPrivilege: "host",
        invitedBypassApproval: false,
        ...overrides,
    };
}

export const EVENTS: Record<string, ReturnType<typeof makeEvent>> = {
    "event-solstice": makeEvent(),
    "event-equinox": makeEvent({
        id: "event-equinox",
        name: "Equinox Warehouse",
        description: "Balanced light.",
        // Its own document, so that a draft which carried one event's document
        // into another's form is a different answer rather than the same one.
        waiver: { url: `${IMG}/equinox-waiver.pdf`, signDate: null },
        questionnaires: [{ id: "q-arrive", question: "Arrival time?", description: null, ordering: 0, isRequired: false }],
        // Free entry, so this one can be submitted without the payment setup
        // the ticketed flow insists on.
        eventType: "rsvpOnly",
        tickets: [ticket("tk-rsvp", "RSVP", 0, 0)],
    }),
};
