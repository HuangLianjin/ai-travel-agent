const { createApp } = Vue;

const apiBase = "/api";

function authHeaders() {
  const token = localStorage.getItem("token") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function refreshTokens() {
  const rt = localStorage.getItem("refresh_token");
  if (!rt) return false;
  const res = await fetch(`${apiBase}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  localStorage.setItem("token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return true;
}

async function request(path, options = {}, retry = true) {
  const res = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401 && retry && (await refreshTokens())) {
    return request(path, options, false);
  }
  if (res.status === 401) {
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("user");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
  return data;
}

createApp({
  data() {
    return {
      token: localStorage.getItem("token") || "",
      user: JSON.parse(localStorage.getItem("user") || "null"),
      profile: null,
      profileModal: false,
      profileDraft: { nickname: "", avatar: "" },
      profileAvatarFile: null,
      profileAvatarPreview: "",
      viewUserProfile: null,
      userProfileModal: false,
      followSaving: false,
      authMode: "login",
      authUsername: "",
      authPassword: "",
      authPhone: "",
      authConfirm: "",
      authCode: "",
      codeSending: false,
      authError: "",
      authNotice: "",
      show2fa: false,
      twofaCode: "",
      verifyPhoneModal: false,
      verifyPhoneCode: "",
      securityModal: false,
      securityTab: "password",
      forcePasswordChange: false,
      changeOldPassword: "",
      changeNewPassword: "",
      changeConfirmPassword: "",
      pendingTotpSecret: "",
      pendingTotpUri: "",
      totpSetupCode: "",
      totpDisableCode: "",
      sessionId: localStorage.getItem("sessionId") || "",
      view: "plan",
      chatInput: "",
      chatLog: [],
      sending: false,
      streamStatus: "",
      tripId: "",
      trip: null,
      tripSource: "",
      dayPage: 1,
      dayPages: 1,
      trips: [],
      tripPage: 1,
      tripPages: 1,
      tripTotal: 0,
      tripPageSize: 5,
      guides: [],
      guidePage: 1,
      guidePages: 1,
      guideTotal: 0,
      guidePageSize: 4,
      guideCity: "",
      guideKeyword: "",
      guideSort: "hot",
      favorites: [],
      favoritePage: 1,
      favoritePages: 1,
      favoriteTotal: 0,
      favoritePageSize: 6,
      likedGuides: [],
      likedPage: 1,
      likedPages: 1,
      likedTotal: 0,
      favTab: "favorited",
      showGuideModal: false,
      guideSaving: false,
      showMyGuidesModal: false,
      viewGuide: null,
      viewGuideModal: false,
      guideComment: "",
      myGuides: [],
      myGuidePage: 1,
      myGuidePages: 1,
      myGuideTotal: 0,
      guideDraft: { title: "", city: "", content: "", feelings: "", trip_id: "", images: [] },
      adminTab: "reviews",
      reviews: [],
      users: [],
      auditLogs: [],
      priceReferences: [],
      priceFeedback: [],
      priceDraft: { place_name: "", city: "", price: "", source: "人工维护", source_url: "", note: "" },
      metrics: null,
      agentRuns: [],
      evalReport: null,
      liveAlerts: [],
      toast: "",
    };
  },
  computed: {
    isAdmin() {
      return this.user && ["admin", "super_admin"].includes(this.user.role);
    },
    currentUserText() {
      return this.user ? `${this.user.username} · ${this.user.role}` : "";
    },
    currentDay() {
      if (!this.trip || !this.trip.days || !this.trip.days.length) return null;
      return this.trip.days[this.dayPage - 1] || this.trip.days[0];
    },
    todayIso() {
      const t = this.trip;
      if (!t || !t.params || !t.params.departure_date) return "";
      const start = new Date(`${t.params.departure_date}T00:00:00`);
      const day = new Date(start.getTime() + (this.dayPage - 1) * 86400000);
      return this.toLocalDate(day);
    },
    currentDayWeather() {
      const t = this.trip;
      if (!t || !t.params || !t.params.departure_date) return null;
      const iso = this.todayIso;
      return (t.weather || []).find(w => w.date === iso) || null;
    },
    currentDayWeatherNotice() {
      const t = this.trip;
      if (!t || !t.params || !t.params.departure_date) return "";
      if (this.currentDayWeather) return "";
      const iso = this.todayIso;
      const missing = (t.weather_missing || []).find(m => m.date === iso);
      if (missing && missing.reason) return missing.reason;
      if (t.weather_notice) return t.weather_notice;
      const max = Number(t.weather_max_days) || 10;
      const offset = Math.floor((new Date(`${iso}T00:00:00`).getTime() - new Date(`${t.params.departure_date}T00:00:00`).getTime()) / 86400000);
      if (offset >= max) return `${this.formatDate(iso)} 已超出当前实时预报范围（约 ${max} 天内），暂无法提供该日准确天气，建议出发前 1-3 天再查询。`;
      return "当天实时天气暂时无法获取，请稍后再试。";
    },
    endDate() {
      const t = this.trip;
      if (!t || !t.params || !t.params.departure_date) return "";
      const start = new Date(`${t.params.departure_date}T00:00:00`);
      const days = (t.params && t.params.days) || (t.days && t.days.length) || 1;
      return this.toLocalDate(new Date(start.getTime() + (days - 1) * 86400000));
    },
    viewTitle() {
      const map = { plan: "AI 行程规划", trips: "我的行程", guides: "攻略广场", favorites: "我的收藏", admin: "管理后台", metrics: "运行指标" };
      return map[this.view] || "星旅 Agent";
    },
  },
  methods: {
    toastMsg(msg) {
      this.toast = msg;
      setTimeout(() => (this.toast = ""), 2600);
    },
    async loadMyProfile() {
      try {
        this.profile = await request("/profile/me");
      } catch (e) {
        this.profile = null;
      }
    },
    openProfileModal() {
      if (!this.profile) return;
      this.profileDraft = { nickname: this.profile.nickname || "", avatar: this.profile.avatar || "" };
      this.profileAvatarFile = null;
      this.profileAvatarPreview = "";
      this.profileModal = true;
      this.$nextTick(() => lucide.createIcons());
    },
    closeProfileModal() {
      this.profileModal = false;
      this.releaseAvatarPreview();
    },
    onProfileAvatar(e) {
      this.releaseAvatarPreview();
      this.profileAvatarFile = e.target.files[0] || null;
      if (this.profileAvatarFile) {
        this.profileAvatarPreview = URL.createObjectURL(this.profileAvatarFile);
      }
    },
    releaseAvatarPreview() {
      if (this.profileAvatarPreview) {
        URL.revokeObjectURL(this.profileAvatarPreview);
        this.profileAvatarPreview = "";
      }
    },
    async saveProfile() {
      try {
        let avatar = this.profileDraft.avatar || (this.profile && this.profile.avatar) || "";
        if (this.profileAvatarFile) {
          const fd = new FormData();
          fd.append("file", this.profileAvatarFile);
          const res = await fetch(`${apiBase}/profile/me/avatar`, {
            method: "POST",
            headers: authHeaders(),
            body: fd,
          });
          if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            throw new Error(d.detail || `上传失败 (${res.status})`);
          }
          avatar = (await res.json()).avatar;
        }
        const updated = await request("/profile/me", {
          method: "PUT",
          body: JSON.stringify({ nickname: this.profileDraft.nickname, avatar }),
        });
        this.closeProfileModal();
        this.profile = updated;
        this.toastMsg("个人资料已保存");
      } catch (e) {
        this.releaseAvatarPreview();
        alert(e.message);
      }
    },
    async openUserProfile(userId) {
      const data = await request(`/users/${userId}/profile`);
      this.viewUserProfile = data;
      this.userProfileModal = true;
      this.$nextTick(() => lucide.createIcons());
    },
    closeUserProfile() {
      this.userProfileModal = false;
      this.viewUserProfile = null;
    },
    async toggleFollow(profile) {
      if (!profile || this.followSaving) return;
      this.followSaving = true;
      try {
        const data = await request(`/users/${profile.user_id || profile.id}/follow`, {
          method: "POST",
          body: JSON.stringify({ follow: !profile.is_following }),
        });
        profile.is_following = data.is_following;
        profile.followers_count = data.followers_count;
      } catch (e) {
        this.releaseAvatarPreview();
        alert(e.message);
      } finally {
        this.followSaving = false;
      }
    },
    async login() {
      try {
        this.authError = "";
        const data = await request("/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: this.authUsername,
            password: this.authPassword,
            totp_code: this.show2fa ? this.twofaCode : "",
          }),
        });
        this.token = data.access_token;
        this.user = data.user;
        localStorage.setItem("token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token || "");
        localStorage.setItem("user", JSON.stringify(data.user));
        this.show2fa = false;
        this.twofaCode = "";
        this.authNotice = "";
        if (!this.sessionId) {
          this.sessionId = (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random()}`;
          localStorage.setItem("sessionId", this.sessionId);
        }
        this.loadMyProfile();
        if (data.must_change_password) {
          this.forcePasswordChange = true;
          this.openSecurityModal("password");
        } else if (!(data.phone_verified || data.email_verified)) {
          this.verifyPhoneModal = true;
        } else if (this.isAdmin) {
          this.view = "admin";
          this.loadAdmin();
        } else {
          this.loadAll();
        }
      } catch (e) {
        this.releaseAvatarPreview();
        if (e.message && e.message.includes("动态验证码")) this.show2fa = true;
        this.authError = e.message;
      }
    },
    async sendRegisterCode() {
      try {
        this.authError = "";
        this.codeSending = true;
        await request("/auth/send-code", {
          method: "POST",
          body: JSON.stringify({ phone: this.authPhone, purpose: "register" }),
        });
        this.authNotice = "验证码已发送（本地开发模式见服务端日志）";
      } catch (e) {
        this.authError = e.message;
      } finally {
        this.codeSending = false;
      }
    },
    async register() {
      try {
        this.authError = "";
        if (this.authPassword !== this.authConfirm) {
          this.authError = "两次输入的密码不一致";
          return;
        }
        await request("/auth/register", {
          method: "POST",
          body: JSON.stringify({
            username: this.authUsername,
            password: this.authPassword,
            phone: this.authPhone,
            code: this.authCode,
          }),
        });
        this.authMode = "login";
        this.authNotice = "注册成功，请登录";
        this.authUsername = "";
        this.authPassword = "";
        this.authConfirm = "";
        this.authCode = "";
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async sendVerifyPhoneCode() {
      try {
        this.authError = "";
        const phone = (this.user && this.user.phone) || (this.profile && this.profile.phone) || "";
        await request("/auth/send-code", {
          method: "POST",
          body: JSON.stringify({ phone, purpose: "verify" }),
        });
        this.toastMsg("验证码已发送");
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async verifyPhone() {
      try {
        this.authError = "";
        await request("/auth/verify-phone", {
          method: "POST",
          body: JSON.stringify({ code: this.verifyPhoneCode }),
        });
        this.verifyPhoneModal = false;
        this.verifyPhoneCode = "";
        this.toastMsg("手机号验证成功");
        if (this.isAdmin) {
          this.view = "admin";
          this.loadAdmin();
        } else {
          this.loadAll();
        }
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async sendResetCode() {
      try {
        this.authError = "";
        this.codeSending = true;
        await request("/auth/send-code", {
          method: "POST",
          body: JSON.stringify({ phone: this.authPhone, purpose: "reset" }),
        });
        this.authNotice = "验证码已发送（本地开发模式见服务端日志）";
      } catch (e) {
        this.authError = e.message;
      } finally {
        this.codeSending = false;
      }
    },
    async forgotPassword() {
      try {
        this.authError = "";
        await request("/auth/forgot-password", {
          method: "POST",
          body: JSON.stringify({ phone: this.authPhone }),
        });
        this.authMode = "reset";
        this.authNotice = "如果该手机号已注册，验证码已发送";
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async resetPassword() {
      try {
        this.authError = "";
        if (this.authPassword !== this.authConfirm) {
          this.authError = "两次输入的密码不一致";
          return;
        }
        await request("/auth/reset-password", {
          method: "POST",
          body: JSON.stringify({
            phone: this.authPhone,
            code: this.authCode,
            new_password: this.authPassword,
          }),
        });
        this.authMode = "login";
        this.authNotice = "密码已重置，请重新登录";
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async logout() {
      const rt = localStorage.getItem("refresh_token");
      if (rt) {
        try {
          await fetch(`${apiBase}/auth/logout`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: rt }),
          });
        } catch (e) {}
      }
      localStorage.removeItem("token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("user");
      location.reload();
    },
    openSecurityModal(tab) {
      this.securityTab = tab || "password";
      this.securityModal = true;
      this.authError = "";
      this.$nextTick(() => lucide.createIcons());
    },
    closeSecurityModal() {
      this.securityModal = false;
      this.forcePasswordChange = false;
    },
    async changePassword() {
      try {
        this.authError = "";
        if (this.changeNewPassword !== this.changeConfirmPassword) {
          this.authError = "两次输入的新密码不一致";
          return;
        }
        await request("/auth/change-password", {
          method: "POST",
          body: JSON.stringify({
            old_password: this.changeOldPassword,
            new_password: this.changeNewPassword,
          }),
        });
        this.changeOldPassword = "";
        this.changeNewPassword = "";
        this.changeConfirmPassword = "";
        this.toastMsg("密码修改成功");
        this.closeSecurityModal();
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async setup2fa() {
      try {
        this.authError = "";
        const data = await request("/auth/2fa/setup");
        this.pendingTotpSecret = data.secret;
        this.pendingTotpUri = data.uri;
        this.securityTab = "2fa_setup";
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async enable2fa() {
      try {
        this.authError = "";
        await request("/auth/2fa/enable", {
          method: "POST",
          body: JSON.stringify({ secret: this.pendingTotpSecret, code: this.totpSetupCode }),
        });
        this.totpSetupCode = "";
        this.securityTab = "password";
        this.toastMsg("动态口令已开启");
        this.loadMyProfile();
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    async disable2fa() {
      try {
        this.authError = "";
        await request("/auth/2fa/disable", {
          method: "POST",
          body: JSON.stringify({ code: this.totpDisableCode }),
        });
        this.totpDisableCode = "";
        this.securityTab = "password";
        this.toastMsg("动态口令已关闭");
        this.loadMyProfile();
      } catch (e) {
        this.releaseAvatarPreview();
        this.authError = e.message;
      }
    },
    switchView(view) {
      this.view = view;
      if (view === "trips") this.loadTrips();
      if (view === "guides") {
        this.guidePage = 1;
        this.loadTrips();
        this.loadGuides();
      }
      if (view === "favorites") {
        this.favoritePage = 1;
        this.likedPage = 1;
        this.loadFavorites();
        this.loadLikedGuides();
      }
      if (view === "admin") this.loadAdmin();
      if (view === "metrics") this.loadMetrics();
      this.$nextTick(() => lucide.createIcons());
    },
    async loadAll() {
      await Promise.all([this.loadTrips(), this.loadGuides(), this.loadFavorites()]);
    },
    async loadTrips() {
      const data = await request(`/trips?page=${this.tripPage}&page_size=${this.tripPageSize}`);
      this.trips = data.items || [];
      this.tripTotal = data.total || 0;
      this.tripPages = data.pages || 1;
    },
    async goTripPage(page) {
      if (page < 1 || page > this.tripPages) return;
      this.tripPage = page;
      await this.loadTrips();
    },
    async deleteTrip(trip) {
      if (!confirm(`确定删除行程「${trip.title}」吗？删除后无法恢复。`)) return;
      await request(`/trips/${trip.id}`, { method: "DELETE" });
      if (this.tripId === trip.id) {
        this.tripId = "";
        this.trip = null;
      }
      await this.loadTrips();
      if (this.trips.length === 0 && this.tripPage > 1) {
        this.tripPage -= 1;
        await this.loadTrips();
      }
      this.toastMsg("行程已删除");
    },
    async loadGuides() {
      const qs = new URLSearchParams({
        status: "approved",
        page: this.guidePage,
        page_size: this.guidePageSize,
        city: this.guideCity || "",
        keyword: this.guideKeyword || "",
        sort: this.guideSort || "hot",
      });
      const data = await request(`/guides?${qs.toString()}`);
      this.guides = data.items || [];
      this.guideTotal = data.total || 0;
      this.guidePages = data.pages || 1;
    },
    mapLink(item) {
      const city = (this.trip && this.trip.city) || (this.viewGuide && this.viewGuide.city) || "";
      const name = item.name || item.title || "";
      return item.map_url || `https://uri.amap.com/search?keyword=${encodeURIComponent(name)}&city=${encodeURIComponent(city)}`;
    },
    async copyGuideTrip() {
      if (!this.viewGuide || !this.viewGuide.trip_itinerary) return;
      await request(`/guides/${this.viewGuide.id}/copy-trip`, { method: "POST" });
      this.toastMsg("攻略行程已加入我的行程");
      await this.loadTrips();
    },
    async goGuidePage(page) {
      if (page < 1 || page > this.guidePages) return;
      this.guidePage = page;
      await this.loadGuides();
      this.$nextTick(() => {
        const el = this.$refs.guidesPanel;
        if (el) {
          window.scrollTo({
            top: el.getBoundingClientRect().top + window.scrollY - 12,
            behavior: "auto",
          });
        }
      });
    },
    async loadFavorites() {
      const data = await request(`/favorites?page=${this.favoritePage}&page_size=${this.favoritePageSize}`);
      this.favorites = data.items || [];
      this.favoriteTotal = data.total || 0;
      this.favoritePages = data.pages || 1;
    },
    async goFavoritePage(page) {
      if (page < 1 || page > this.favoritePages) return;
      this.favoritePage = page;
      await this.loadFavorites();
    },
    async loadLikedGuides() {
      const data = await request(`/guides/liked?page=${this.likedPage}&page_size=6`);
      this.likedGuides = data.items || [];
      this.likedTotal = data.total || 0;
      this.likedPages = data.pages || 1;
    },
    async goLikedPage(page) {
      if (page < 1 || page > this.likedPages) return;
      this.likedPage = page;
      await this.loadLikedGuides();
    },
    async loadAdmin() {
      const [reviews, users, logs, slots, prices, feedback] = await Promise.all([
        request("/admin/reviews"),
        request("/admin/users"),
        request("/admin/audit-logs"),
        request("/admin/recommend-slots"),
        request("/admin/prices"),
        request("/admin/price-feedback"),
      ]);
      this.reviews = reviews;
      this.users = users;
      this.auditLogs = logs;
      this.priceReferences = prices || [];
      this.priceFeedback = feedback || [];
    },
    async savePrice() {
      if (!this.priceDraft.place_name.trim() || !this.priceDraft.price) {
        alert("地点和价格不能为空");
        return;
      }
      await request("/admin/prices", {
        method: "POST",
        body: JSON.stringify({ ...this.priceDraft, price: Number(this.priceDraft.price) }),
      });
      this.priceDraft = { place_name: "", city: "", price: "", source: "人工维护", source_url: "", note: "" };
      await this.loadAdmin();
      this.toastMsg("价格已保存");
    },
    async deletePrice(id) {
      await request(`/admin/prices/${id}`, { method: "DELETE" });
      await this.loadAdmin();
    },
    async decidePriceFeedback(fb, status) {
      await request(`/admin/price-feedback/${fb.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await this.loadAdmin();
      this.toastMsg(status === "approved" ? "反馈已采用" : "反馈已驳回");
    },
    async loadMetrics() {
      const [m, runs] = await Promise.all([
        request("/metrics"),
        request("/admin/runs?page=1&page_size=20"),
      ]);
      this.metrics = m;
      this.agentRuns = (runs && runs.items) || [];
    },
    async loadLiveAlerts() {
      if (!this.tripId) {
        this.liveAlerts = [];
        return;
      }
      try {
        const data = await request(`/trips/${this.tripId}/live-alerts`);
        this.liveAlerts = data.alerts || [];
        if (data.itinerary) {
          this.trip = data.itinerary;
          await this.setDayPagination(data.itinerary);
        }
      } catch (e) {
        this.liveAlerts = [];
      }
    },
    toLocalDate(d) {
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    },
    formatDateTime(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      const pad = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },
    statusText(status) {
      const map = { pending: "待审核", approved: "已通过", rejected: "已驳回", published: "已发布" };
      return map[status] || status;
    },
    tripEndDate(t) {
      const it = t.itinerary || {};
      const start = it.params && it.params.departure_date;
      if (!start) return "";
      const days = (it.params && it.params.days) || (it.days && it.days.length) || 1;
      return this.toLocalDate(new Date(new Date(`${start}T00:00:00`).getTime() + (days - 1) * 86400000));
    },
    formatDate(iso) {
      if (!iso) return "";
      const d = new Date(`${iso}T00:00:00`);
      return `${d.getMonth() + 1}月${d.getDate()}日`;
    },
    async changeDepartureDate() {
      if (!this.tripId || !this.trip) return;
      const val = prompt("请输入新的出发日期（例如：8月25号、后天、2026-08-25）：");
      if (!val) return;
      this.chatInput = `出发日期改成 ${val}`;
      await this.sendMessage();
    },
    transportModeName(mode) {
      const map = { auto: "自动推荐", car: "打车", bus: "公交", ride: "骑行", walk: "步行", 公共交通: "公共交通", 公交: "公交", 地铁: "地铁", 共享单车: "共享单车", 骑行: "骑行", 打车: "打车", 驾车: "驾车" };
      return map[mode] || mode || "自动推荐";
    },
    transportCost(t) {
      const n = Number((this.trip && this.trip.params && this.trip.params.travelers) || 1);
      const unit = Number(t.cost_yuan) || 0;
      const mode = t.mode || "";
      if (["打车", "驾车", "car", "drive"].includes(mode)) {
        return Math.round(unit * Math.max(1, Math.ceil(n / 4)));
      }
      if (["公共交通", "公交", "地铁", "共享单车", "骑行", "bus", "ride"].includes(mode)) {
        return Math.round(unit * n);
      }
      return unit;
    },
    escapeHtml(s) {
      return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    },
    amapNavUrl(leg) {
      const modes = { 公共交通: "bus", 公交: "bus", 地铁: "bus", 共享单车: "ride", 骑行: "ride", 打车: "car", 驾车: "car", 自驾: "car" };
      const mode = modes[leg.mode] || "car";
      if (leg.from_lon && leg.from_lat && leg.to_lon && leg.to_lat) {
        return `https://uri.amap.com/navigation?from=${leg.from_lon},${leg.from_lat}&to=${leg.to_lon},${leg.to_lat}&mode=${mode}`;
      }
      const city = (this.trip && this.trip.city) || "";
      return `https://ditu.amap.com/search?query=${encodeURIComponent(leg.to || "")}&city=${encodeURIComponent(city)}`;
    },
    buildTripText() {
      const t = this.trip;
      if (!t) return "";
      const p = t.params || {};
      const lines = [t.summary || `${t.city || ""} 行程`, ""];
      lines.push(`目的地：${t.city || ""} · ${(t.days || []).length || p.days || 1} 天 · ${p.travelers || 1} 人`);
      if (p.departure_date) {
        lines.push(`出行日期：${this.formatDate(p.departure_date)} 至 ${this.formatDate(this.endDate)}`);
      }
      if (p.budget) lines.push(`预算：¥${p.budget}`);
      if (t.weather && t.weather.length) {
        lines.push("天气：");
        t.weather.forEach((w) => {
          lines.push(`- ${this.formatDate(w.date)} ${w.text} ${w.temp_min}~${w.temp_max}℃`);
        });
      }
      lines.push("");
      (t.days || []).forEach((day) => {
        lines.push(`Day ${day.day} 【${day.theme || "漫游"}】`);
        const daily = t.budget && t.budget.daily_totals && t.budget.daily_totals[day.day - 1];
        if (daily) {
          lines.push(`当天消费：门票 ¥${daily.attractions} + 餐饮 ¥${daily.dining} + 交通 ¥${daily.transport} = ¥${daily.total}`);
        }
        (day.timeline || []).forEach((item) => {
          const typeLabel = item.type === "attraction" ? "景点" : item.type === "food" ? "美食" : item.type === "transport" ? "交通" : item.type === "hotel_return" ? "回酒店" : item.type === "rest" ? "休息" : "其他";
          let line = `${item.time} ${typeLabel} ${item.restaurant ? item.restaurant + "（" + item.title + "）" : item.title}`;
          if (item.mode && item.type === "transport") {
            line += ` · ${this.transportModeName(item.mode)} · ${item.minutes}分钟`;
            if (item.cost_yuan != null) line += ` · ¥${this.transportCost(item)}`;
          }
          if (item.type !== "transport" && item.price) {
            line += ` · 约¥${item.price * (p.travelers || 1)}${(p.travelers || 1) > 1 ? `（${p.travelers}人）` : ""}`;
          }
          if (item.address) line += ` · 地址：${item.address}`;
          if (item.note) line += ` · ${item.note}`;
          lines.push(line);
        });
        lines.push("");
      });
      if (t.hotel_options && t.hotel_options.length) {
        lines.push("住宿建议：");
        t.hotel_options.slice(0, 3).forEach((h) => {
          lines.push(`- ${h.name}（${h.room_type || "大床房"} · ${h.price != null ? "¥" + h.price + "/晚" : "价格待询"}）`);
        });
        lines.push("");
      }
      if (t.practical_tips && t.practical_tips.length) {
        lines.push(`实用信息：${t.practical_tips.join("；")}`);
      }
      if (t.packing_list && t.packing_list.length) {
        lines.push(`携带清单：${t.packing_list.join("、")}`);
      }
      if (t.budget && t.budget.estimated_total != null) {
        lines.push(`总消费：¥${t.budget.estimated_total}${p.budget ? ` / 预算 ¥${p.budget}` : ""}`);
      }
      return lines.join("\n");
    },
    async copyTrip() {
      const text = this.buildTripText();
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        this.toastMsg("攻略文本已复制");
      } catch (e) {
        prompt("复制失败，请手动复制：", text);
      }
    },
    downloadICS() {
      const t = this.trip;
      if (!t || !t.days) return;
      const start = (t.params && t.params.departure_date) || new Date().toISOString().slice(0, 10);
      const base = new Date(`${start}T00:00:00`);
      const vevents = (t.days || []).map((day, i) => {
        const d = new Date(base.getTime() + i * 86400000);
        const ymd = this.toLocalDate(d).replace(/-/g, "");
        const attrs = (day.attractions || []).map((a) => a.name).join(" → ");
        const foods = (day.dining || []).map((f) => f.name).join("、");
        const desc = `Day ${day.day} ${day.theme || ""} 景点：${attrs} 餐饮：${foods}`.replace(/[,;\n]/g, " ");
        return [
          "BEGIN:VEVENT",
          `UID:${Date.now()}-${day.day}@startravel`,
          `DTSTART;VALUE=DATE:${ymd}`,
          `SUMMARY:${`${t.city || ""} Day${day.day} ${day.theme || ""}`.replace(/[,;\n]/g, " ")}`,
          `DESCRIPTION:${desc}`,
          "END:VEVENT",
        ].join("\r\n");
      });
      const ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//StarTravel//CN", ...vevents, "END:VCALENDAR"].join("\r\n");
      const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${t.city || "行程"}-${start}.ics`;
      a.click();
      URL.revokeObjectURL(url);
    },
    printTrip() {
      const text = this.buildTripText();
      if (!text) return;
      const title = `${this.trip && this.trip.city ? this.trip.city : "行程"} 攻略`;
      const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${this.escapeHtml(title)}</title><style>body{font-family:"Microsoft YaHei",sans-serif;padding:28px;line-height:1.8;color:#111;max-width:900px;margin:0 auto}pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:14px}</style></head><body><pre>${this.escapeHtml(text)}</pre></body></html>`;
      const iframe = document.createElement("iframe");
      iframe.style.position = "fixed";
      iframe.style.right = "0";
      iframe.style.bottom = "0";
      iframe.style.width = "0";
      iframe.style.height = "0";
      iframe.style.border = "0";
      document.body.appendChild(iframe);
      const doc = iframe.contentWindow.document;
      doc.open();
      doc.write(html);
      doc.close();
      iframe.contentWindow.focus();
      iframe.contentWindow.print();
      setTimeout(() => iframe.remove(), 1000);
    },
    async sendMessage() {
      const text = this.chatInput.trim();
      if (!text || this.sending) return;
      this.chatLog.push({ role: "user", content: text });
      this.chatLog.push({ role: "assistant", content: "" });
      this.chatInput = "";
      this.sending = true;
      this.streamStatus = "正在准备...";
      try {
        const res = await fetch(`${apiBase}/chat?stream=true`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ message: text, trip_id: this.tripId, session_id: this.sessionId }),
        });
        if (!res.ok || !res.body) {
          let msg = `请求失败 (${res.status})`;
          try {
            const d = await res.json();
            msg = d.detail || msg;
          } catch {}
          throw new Error(msg);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const dataLine = raw
              .split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).trim())
              .join("");
            if (!dataLine) continue;
            let ev;
            try {
              ev = JSON.parse(dataLine);
            } catch {
              continue;
            }
            if (ev.type === "stage") {
              this.streamStatus = ev.status === "start" ? `${ev.label} 执行中...` : `${ev.label} 完成`;
            } else if (ev.token !== undefined) {
              const last = this.chatLog[this.chatLog.length - 1];
              last.content += ev.token;
              this.chatLog.splice(this.chatLog.length - 1, 1, { ...last });
            } else if (ev.done) {
              this.trip = ev.itinerary;
              this.tripId = ev.trip_id || this.tripId;
              this.tripSource = "create";
              await this.setDayPagination(ev.itinerary);
              this.streamStatus = "";
              await this.loadTrips();
              await this.loadLiveAlerts();
            } else if (ev.error) {
              this.chatLog.push({ role: "ai", content: `出错了：${ev.message}` });
            }
          }
        }
      } catch (e) {
        this.chatLog.push({ role: "ai", content: `出错了：${e.message}` });
      } finally {
        this.sending = false;
        this.streamStatus = "";
      }
    },
    async setDayPagination(plan) {
      const days = (plan && plan.days) || [];
      this.dayPages = Math.max(1, days.length);
      this.dayPage = Math.min(this.dayPage, this.dayPages) || 1;
    },
    async goDayPage(page) {
      if (page < 1 || page > this.dayPages) return;
      this.dayPage = page;
      this.$nextTick(() => {
        const card = this.$refs.tripCard;
        if (card) card.scrollTop = 0;
      });
    },
    newTrip() {
      if (this.sending) return;
      this.tripId = "";
      this.trip = null;
      this.tripSource = "";
      this.dayPage = 1;
      this.dayPages = 1;
      this.liveAlerts = [];
      this.chatLog = [];
      this.sessionId = (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random()}`;
      localStorage.setItem("sessionId", this.sessionId);
      this.$nextTick(() => lucide.createIcons());
      this.toastMsg("已开始新建行程");
    },
    async openTrip(trip) {
      this.trip = trip.itinerary;
      this.tripId = trip.id;
      this.tripSource = "open";
      await this.setDayPagination(trip.itinerary);
      this.view = "plan";
      this.chatLog = [
        { role: "ai", content: `已载入：${trip.title}\n可以继续对我说“当天轻松一些”“增加火锅”等调整。` },
      ];
      await this.loadLiveAlerts();
    },
    async publishTrip() {
      try {
        await request(`/trips/${this.tripId}/publish`, { method: "POST" });
        this.toastMsg("行程已发布");
        this.loadTrips();
      } catch (e) {
        this.releaseAvatarPreview();
        alert(e.message);
      } finally {
        this.guideSaving = false;
      }
    },
    async loadMyGuides() {
      const data = await request(`/guides/mine?page=${this.myGuidePage}&page_size=6`);
      this.myGuides = data.items || [];
      this.myGuideTotal = data.total || 0;
      this.myGuidePages = data.pages || 1;
    },
    async goMyGuidePage(page) {
      if (page < 1 || page > this.myGuidePages) return;
      this.myGuidePage = page;
      await this.loadMyGuides();
    },
    onGuideImages(e) {
      this.releaseGuidePreviews();
      this.guideDraft.images = Array.from(e.target.files || []).map((f) => ({
        file: f,
        name: f.name,
        size: f.size,
        preview: URL.createObjectURL(f),
      }));
    },
    releaseGuidePreviews() {
      (this.guideDraft.images || []).forEach((img) => {
        if (img.preview) URL.revokeObjectURL(img.preview);
      });
      this.guideDraft.images = [];
    },
    onSelectGuideTrip() {
      const t = this.trips.find((x) => x.id === this.guideDraft.trip_id);
      if (t) this.guideDraft.city = t.city;
    },
    openGuideModal() {
      this.showGuideModal = true;
      this.$nextTick(() => lucide.createIcons());
    },
    closeGuideModal() {
      this.releaseGuidePreviews();
      this.showGuideModal = false;
    },
    openMyGuidesModal() {
      this.myGuidePage = 1;
      this.loadMyGuides();
      this.showMyGuidesModal = true;
      this.$nextTick(() => lucide.createIcons());
    },
    closeMyGuidesModal() {
      this.showMyGuidesModal = false;
    },
    async openGuide(guide) {
      const data = await request(`/guides/${guide.id}`);
      this.viewGuide = data;
      this.viewGuideModal = true;
      this.$nextTick(() => lucide.createIcons());
    },
    closeGuideDetail() {
      this.viewGuideModal = false;
      this.viewGuide = null;
      this.guideComment = "";
    },
    async loadGuideDetail() {
      if (!this.viewGuide) return;
      const data = await request(`/guides/${this.viewGuide.id}`);
      this.viewGuide = data;
    },
    async feedbackPrice(item) {
      const name = item.title || item.name || "";
      if (!name) return;
      const city = (this.trip && this.trip.city) || "";
      const input = prompt(`反馈 ${name} 的实际价格（元）：`);
      if (!input) return;
      const price = Number(input);
      if (!price || price <= 0) {
        alert("请输入有效价格");
        return;
      }
      await request("/prices/feedback", {
        method: "POST",
        body: JSON.stringify({ place_name: name, city, price }),
      });
      this.toastMsg("价格反馈已提交，等待管理员审核");
    },
    async addGuideComment() {
      if (!this.viewGuide || !this.guideComment.trim()) return;
      await request(`/guides/${this.viewGuide.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ content: this.guideComment }),
      });
      this.guideComment = "";
      await this.loadGuideDetail();
    },
    async createGuide() {
      if (this.guideSaving) return;
      try {
        if (!this.guideDraft.title.trim() || !this.guideDraft.content.trim()) {
          alert("标题和内容不能为空");
          return;
        }
        if (!this.guideDraft.feelings.trim()) {
          alert("请填写游玩感受，例如哪里最值得去、体验如何");
          return;
        }
        this.guideSaving = true;
        const fd = new FormData();
        fd.append("title", this.guideDraft.title);
        fd.append("content", `${this.guideDraft.content.trim()}\n\n【游玩感受】\n${this.guideDraft.feelings.trim()}`);
        fd.append("trip_id", this.guideDraft.trip_id);
        fd.append("city", this.guideDraft.city);
        (this.guideDraft.images || []).forEach((f) => fd.append("images", f.file));
        const res = await fetch(`${apiBase}/guides/upload`, {
          method: "POST",
          headers: authHeaders(),
          body: fd,
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.detail || `请求失败 (${res.status})`);
        }
        this.guideDraft = { title: "", city: "", content: "", feelings: "", trip_id: "", images: [] };
        this.closeGuideModal();
        this.toastMsg("攻略已提交，等待管理员审核");
        this.loadMyGuides();
      } catch (e) {
        this.releaseAvatarPreview();
        alert(e.message);
      }
    },
    async likeGuide(guide) {
      if (guide._likeBusy) return;
      const prevLiked = !!guide.liked_by_me;
      const prevLikes = guide.likes || 0;
      const next = !prevLiked;
      guide.liked_by_me = next;
      guide.likes = next ? prevLikes + 1 : Math.max(0, prevLikes - 1);
      guide._likeBusy = true;
      try {
        const res = await request(`/guides/${guide.id}/like`, {
          method: "POST",
          body: JSON.stringify({ liked: next }),
        });
        guide.liked_by_me = res.liked;
        guide.likes = res.likes;
        guide.favorites = res.favorites;
      } catch (e) {
        guide.liked_by_me = prevLiked;
        guide.likes = prevLikes;
        alert(e.message);
      } finally {
        guide._likeBusy = false;
        if (this.view === "favorites" && this.favTab === "liked") this.loadLikedGuides();
      }
    },
    async favoriteGuide(guide) {
      if (guide._favBusy) return;
      const prevFav = !!guide.favorited_by_me;
      const prevFavs = guide.favorites || 0;
      const next = !prevFav;
      guide.favorited_by_me = next;
      guide.favorites = next ? prevFavs + 1 : Math.max(0, prevFavs - 1);
      guide._favBusy = true;
      try {
        const res = await request(`/guides/${guide.id}/favorite`, {
          method: "POST",
          body: JSON.stringify({ favorited: next }),
        });
        guide.favorited_by_me = res.favorited;
        guide.favorites = res.favorites;
      } catch (e) {
        guide.favorited_by_me = prevFav;
        guide.favorites = prevFavs;
        alert(e.message);
      } finally {
        guide._favBusy = false;
        if (this.view === "favorites") {
          if (!next) {
            this.favorites = this.favorites.filter((x) => x.id !== guide.id);
            this.favoriteTotal = Math.max(0, this.favoriteTotal - 1);
            this.favoritePages = Math.max(1, Math.ceil(this.favoriteTotal / this.favoritePageSize));
            if (this.favorites.length === 0 && this.favoritePage > 1) {
              this.favoritePage -= 1;
              this.loadFavorites();
            }
          } else if (this.favTab === "favorited") {
            this.loadFavorites();
          }
        }
      }
    },
    switchFavTab(tab) {
      this.favTab = tab;
      if (tab === "favorited" && !this.favorites.length) this.loadFavorites();
      if (tab === "liked" && !this.likedGuides.length) this.loadLikedGuides();
    },
    async decideReview(review, status) {
      const note = prompt(status === "approved" ? "审核意见（可留空）" : "驳回原因");
      if (note === null) return;
      await request(`/admin/reviews/${review.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ status, note }),
      });
      this.loadAdmin();
      this.toastMsg(status === "approved" ? "已通过" : "已驳回");
    },
    async setUserStatus(user, status) {
      await request(`/admin/users/${user.id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      this.loadAdmin();
    },
    async runEval() {
      this.evalReport = await request("/eval/run");
      this.toastMsg("离线评测完成");
    },
  },
  mounted() {
    if (this.token && this.user) {
      if (this.isAdmin) {
        this.view = "admin";
        this.loadAdmin();
      } else {
        this.loadAll();
      }
      this.loadMyProfile();
    }
    this.$nextTick(() => lucide.createIcons());
  },
  updated() {
    clearTimeout(this._iconDebounce);
    this._iconDebounce = setTimeout(() => this.$nextTick(() => lucide.createIcons()), 120);
  },
  template: `
    <div v-if="!token" class="login-page">
      <div class="login-card">
        <div class="brand">
          <span class="logo"><i data-lucide="map"></i></span>
          <span>星旅 Agent</span>
        </div>

        <div v-if="authMode === 'login'">
          <div class="field">
            <label>用户名</label>
            <input v-model="authUsername" placeholder="请输入用户名" />
          </div>
          <div class="field">
            <label>密码</label>
            <input v-model="authPassword" type="password" placeholder="请输入密码" />
          </div>
          <div v-if="show2fa" class="field">
            <label>动态验证码</label>
            <input v-model="twofaCode" placeholder="6 位动态验证码" />
          </div>
          <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
          <p v-if="authNotice" class="small muted" style="margin:6px 0">{{ authNotice }}</p>
          <button class="btn primary block" @click="login"><i data-lucide="log-in"></i> 登录</button>
          <div style="display:flex;justify-content:space-between;margin-top:10px">
            <button class="btn sm" @click="authMode='register'">注册新账号</button>
            <button class="btn sm" @click="authMode='forgot'">忘记密码</button>
          </div>
        </div>

        <div v-else-if="authMode === 'register'">
          <div class="field"><label>用户名</label><input v-model="authUsername" maxlength="32" /></div>
          <div class="field"><label>手机号</label><input v-model="authPhone" maxlength="11" /></div>
          <div class="field">
            <label>验证码</label>
            <div style="display:flex;gap:8px">
              <input v-model="authCode" placeholder="6 位验证码" />
              <button class="btn sm" @click="sendRegisterCode" :disabled="codeSending">{{ codeSending ? '发送中' : '获取验证码' }}</button>
            </div>
          </div>
          <div class="field"><label>密码（8 位以上，含字母和数字）</label><input v-model="authPassword" type="password" /></div>
          <div class="field"><label>确认密码</label><input v-model="authConfirm" type="password" /></div>
          <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
          <p v-if="authNotice" class="small muted" style="margin:6px 0">{{ authNotice }}</p>
          <button class="btn primary block" @click="register">注册</button>
          <button class="btn block" style="margin-top:8px" @click="authMode='login'">返回登录</button>
        </div>

        <div v-else-if="authMode === 'forgot'">
          <div class="field"><label>手机号</label><input v-model="authPhone" maxlength="11" /></div>
          <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
          <p v-if="authNotice" class="small muted" style="margin:6px 0">{{ authNotice }}</p>
          <button class="btn primary block" @click="forgotPassword">发送验证码</button>
          <button class="btn block" style="margin-top:8px" @click="authMode='login'">返回登录</button>
        </div>

        <div v-else>
          <div class="field"><label>手机号</label><input v-model="authPhone" maxlength="11" /></div>
          <div class="field"><label>验证码</label><input v-model="authCode" /></div>
          <div class="field"><label>新密码（8 位以上，含字母和数字）</label><input v-model="authPassword" type="password" /></div>
          <div class="field"><label>确认新密码</label><input v-model="authConfirm" type="password" /></div>
          <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
          <p v-if="authNotice" class="small muted" style="margin:6px 0">{{ authNotice }}</p>
          <button class="btn primary block" @click="resetPassword">重置密码</button>
          <button class="btn block" style="margin-top:8px" @click="authMode='login'">返回登录</button>
        </div>
      </div>
    </div>

    <div v-else class="shell">
      <aside class="sidebar">
        <div class="brand"><span class="logo"><i data-lucide="map"></i></span><span>星旅 Agent</span></div>
        <button v-if="!isAdmin" class="nav-item" :class="{active: view==='plan'}" @click="switchView('plan')"><i data-lucide="compass"></i> 行程规划</button>
        <button v-if="!isAdmin" class="nav-item" :class="{active: view==='trips'}" @click="switchView('trips')"><i data-lucide="briefcase"></i> 我的行程</button>
        <button v-if="!isAdmin" class="nav-item" :class="{active: view==='guides'}" @click="switchView('guides')"><i data-lucide="book-open"></i> 攻略广场</button>
        <button v-if="!isAdmin" class="nav-item" :class="{active: view==='favorites'}" @click="switchView('favorites')"><i data-lucide="heart"></i> 我的收藏</button>
        <button v-if="isAdmin" class="nav-item" :class="{active: view==='metrics'}" @click="switchView('metrics')"><i data-lucide="activity"></i> 指标</button>
        <button v-if="isAdmin" class="nav-item" :class="{active: view==='admin'}" @click="switchView('admin')"><i data-lucide="shield"></i> 管理后台</button>
        <div class="user-box">
          <button class="avatar-btn" @click="openProfileModal">
            <img v-show="profile && profile.avatar" :src="profile.avatar" alt="头像" />
            <i v-show="!profile || !profile.avatar" data-lucide="user"></i>
          </button>
          <div style="min-width:0">
            <div class="small">{{ profile ? (profile.nickname || profile.username) : currentUserText }}</div>
            <div class="small muted" style="margin-top:2px">{{ profile ? profile.username : "" }}</div>
          </div>
          <button class="btn sm" @click="openSecurityModal('password')" style="margin-top:8px"><i data-lucide="shield"></i> 安全</button>
          <button class="btn sm" @click="logout" style="margin-top:8px"><i data-lucide="log-out"></i> 退出</button>
        </div>
      </aside>

      <main class="main">
        <div class="topbar">
          <h1>{{ viewTitle }}</h1>
          <span v-if="toast" class="notice" style="margin:0">{{ toast }}</span>
        </div>
        <div class="content">
          <div v-if="view==='plan'" class="grid cols-2 plan-layout">
            <div class="card chat-panel">
              <div class="panel-title-row">
                <h3>AI 行程规划 <span v-if="tripId && trip" class="small muted">（修改当前行程）</span></h3>
                <button v-if="tripId" class="btn sm" @click="newTrip"><i data-lucide="plus"></i> 新建行程</button>
              </div>
              <div class="chat-log">
                <template v-if="chatLog.length===0">
                  <div class="bubble ai">输入目的地、日期、人数、预算和兴趣，例如：<br/>“北京三天，预算3000，喜欢历史和美食”</div>
                </template>
                <div v-for="(m,i) in chatLog" :key="i" class="bubble" :class="m.role">{{ m.content }}</div>
              </div>
              <div v-if="streamStatus" class="stream-status">{{ streamStatus }}</div>
              <div class="composer">
                <textarea v-model="chatInput" placeholder="继续用自然语言调整，如“当天轻松一些”“增加火锅”“推荐附近酒店”" @keydown.enter.exact.prevent="sendMessage"></textarea>
                <button class="btn primary" @click="sendMessage" :disabled="sending"><i data-lucide="send"></i> 生成</button>
              </div>
            </div>

            <div class="card" v-if="trip" ref="tripCard">
              <div v-if="trip.params && trip.params.departure_date" class="trip-dates">
                <i data-lucide="calendar"></i>
                <div class="trip-date-range">
                  <span>出发：{{ formatDate(trip.params.departure_date) }}</span>
                  <span>游玩至：{{ formatDate(endDate) }}</span>
                </div>
                <button class="btn sm" @click="changeDepartureDate"><i data-lucide="pencil"></i> 修改出发日期</button>
              </div>
              <div class="grid cols-3" style="margin-bottom:12px">
                <div class="metric"><div class="label">城市</div><div class="value">{{ trip.city }}</div></div>
                <div class="metric"><div class="label">天数</div><div class="value">{{ trip.days ? trip.days.length : (trip.summary || '').includes('2 日') ? 2 : 1 }}</div></div>
                <div class="metric"><div class="label">来源约束</div><div class="value">{{ (trip.sources || []).length }}</div></div>
              </div>
              <div v-if="currentDayWeather" class="today-weather">
                <i data-lucide="cloud-sun" style="width:26px;height:26px"></i>
                <div class="today-weather-body">
                  <div class="today-weather-title">{{ formatDate(currentDayWeather.date) }} 当天天气</div>
                  <div class="today-weather-main">{{ currentDayWeather.text }} · {{ currentDayWeather.temp_min }}~{{ currentDayWeather.temp_max }}℃</div>
                  <div v-if="trip.weather_advice" class="small" style="margin-top:4px">{{ trip.weather_advice }}</div>
                  <div v-if="trip.weather_warnings && trip.weather_warnings.length" class="notice">天气预警：<span v-for="ww in trip.weather_warnings" :key="ww.title">{{ ww.title }}</span></div>
                </div>
              </div>
              <div v-else-if="currentDayWeatherNotice" class="today-weather unavailable">
                <i data-lucide="cloud-off" style="width:26px;height:26px"></i>
                <div class="today-weather-body">
                  <div class="today-weather-title">{{ formatDate(todayIso) }} 天气暂不可查</div>
                  <div class="small" style="margin-top:4px">{{ currentDayWeatherNotice }}</div>
                </div>
              </div>

                            <div v-if="currentDay" class="day-block">
                <h4>Day {{ currentDay.day }} · {{ currentDay.theme }}</h4>
                <div v-if="currentDay.timeline && currentDay.timeline.length" class="timeline">
                  <div v-for="(t, i) in currentDay.timeline" :key="i" class="timeline-item" :class="t.type">
                    <span class="tl-time">{{ t.time }}</span>
                    <span class="tl-type">{{ t.type === 'attraction' ? '景点' : t.type === 'food' ? '美食' : t.type === 'photo' ? '拍照' : t.type === 'hotel_return' ? '回酒店' : t.type === 'rest' ? '休息' : '交通' }}</span>
                    <div class="tl-body">
                      <b>{{ t.restaurant ? t.restaurant + '（' + t.title + '）' : t.title }}</b>
                      <span v-if="t.data_label" class="data-badge" :class="'lv-' + (t.data_level || 'C')">{{ t.data_label }}</span>
                      <span v-if="t.mode && t.type === 'transport'" class="muted"> · {{ transportModeName(t.mode) }} · {{ t.minutes }}分钟<template v-if="t.cost_yuan != null"> · ¥{{ transportCost(t) }}</template><template v-if="t.cost_yuan == null"> · 费用待定</template></span>
                      <div v-if="t.steps && t.steps.length" class="muted">换乘：{{ t.steps.join('；') }}</div>
                      <span v-if="t.price && t.type !== 'transport'" class="muted"> · 约 ¥{{ t.price * (trip.params && trip.params.travelers || 1) }}<template v-if="(trip.params && trip.params.travelers || 1) > 1">（{{ trip.params.travelers }}人）</template></span>
                      <div v-if="t.address" class="muted">地址：{{ t.address }}</div>
                      <div v-if="t.note" class="muted">{{ t.note }}</div>
                      <a v-if="t.url" :href="t.url" target="_blank" rel="noopener" class="link-btn"><i data-lucide="ticket"></i> 官方预约</a>
                      <a v-if="t.map_url" :href="t.map_url" target="_blank" rel="noopener" class="link-btn"><i data-lucide="search"></i> 找店</a>
                      <button v-if="t.type === 'attraction' || t.type === 'food'" class="link-btn" @click="feedbackPrice(t)"><i data-lucide="pencil"></i> 反馈价格</button>
                    </div>
                  </div>
                </div>
                <div v-else>
                  <div v-for="item in currentDay.attractions" :key="item.name" class="small" style="padding:4px 0">
                    <b>{{ item.name }}</b>
                    <span v-if="item.data_label" class="data-badge" :class="'lv-' + (item.data_level || 'B')">{{ item.data_label }}</span>
                    <span class="muted"> · {{ item.opening_hours }} · {{ item.fee != null ? item.fee : '待查' }} 元 · {{ item.duration_hours }}h</span>
                    <div class="muted">{{ item.note }}</div>
                    <a v-if="item.official_url" :href="item.official_url" target="_blank" rel="noopener" class="link-btn"><i data-lucide="ticket"></i> 官方预约</a>
                  </div>
                  <div class="small muted" style="margin-top:6px">餐饮：<span v-for="f in currentDay.dining" :key="f.name">{{ f.restaurant ? f.restaurant + '（' + f.name + '）' : f.name }}<span v-if="f.data_label" class="data-badge" :class="'lv-' + (f.data_level || 'B')">{{ f.data_label }}</span>（{{ f.price || f.budget }}元{{ f.price_source === '估算价' || !f.price_source ? '·估算价' : '·' + f.price_source }}）<a v-if="f.map_url" :href="f.map_url" target="_blank" rel="noopener" class="link-btn" style="margin:0 0 0 6px"><i data-lucide="search"></i> 找店</a> </span></div>
                  <div class="route-leg" v-for="leg in currentDay.route" :key="leg.from">
                    <i data-lucide="navigation" style="width:14px"></i>
                    <span>{{ leg.from }} → {{ leg.to }} · {{ leg.distance_km }}km · {{ leg.minutes }}分钟</span>
                    <a :href="amapNavUrl(leg)" target="_blank" rel="noopener" class="link-btn"><i data-lucide="map-pin"></i> 高德导航</a>
                  </div>
                  <div class="cost-line" v-if="trip.budget && trip.budget.daily_totals && trip.budget.daily_totals[currentDay.day-1]">
                    Day {{ currentDay.day }} 消费：门票 ¥{{ trip.budget.daily_totals[currentDay.day-1].attractions }} + 餐饮 ¥{{ trip.budget.daily_totals[currentDay.day-1].dining }} + 交通 ¥{{ trip.budget.daily_totals[currentDay.day-1].transport }} = <b>¥{{ trip.budget.daily_totals[currentDay.day-1].total }}</b>
                  </div>
                </div>
                <div v-if="dayPage === 1 && trip.hotel_options && trip.hotel_options.length" class="hotel-block">
                  <h4>住宿建议</h4>
                  <div v-for="h in trip.hotel_options.slice(0, 3)" :key="h.name" class="small" style="padding:4px 0">
                    <b>{{ h.name }}</b>
                    <span class="muted"> · {{ h.room_type || '大床房' }} · {{ h.price != null ? '¥' + h.price + '/晚' : '价格待询' }}</span>
                    <div v-if="h.address" class="muted">地址：{{ h.address }}</div>
                    <a v-if="h.url" :href="h.url" target="_blank" rel="noopener" class="link-btn"><i data-lucide="external-link"></i> 查看</a>
                  </div>
                  <div class="muted" style="font-size:11px">价格与房态以平台实际为准</div>
                </div>
              </div>
              <div class="pager" v-if="dayPages > 1">
                <button class="btn sm" :disabled="dayPage <= 1" @click="goDayPage(dayPage - 1)">上一页</button>
                <span class="small muted">Day {{ dayPage }} / {{ dayPages }}</span>
                <button class="btn sm" :disabled="dayPage >= dayPages" @click="goDayPage(dayPage + 1)">下一页</button>
              </div>
              <div class="total-cost" v-if="trip.budget">
                <div>总消费：<b>¥{{ trip.budget.estimated_total }}</b>
                <span v-if="trip.params && trip.params.budget"> / 预算 ¥{{ trip.params.budget }}</span>
                <span v-if="trip.budget.within_budget === false" class="muted">（超出预算）</span></div>
                <div class="muted" style="font-size:12px;margin-top:4px">
                  门票 ¥{{ trip.budget.attractions }} + 餐饮 ¥{{ trip.budget.dining }} + 交通 ¥{{ trip.budget.transport }}
                </div>
              </div>
              <div v-if="trip.practical_tips && trip.practical_tips.length" class="tips-block">
                <h4>实用信息</h4>
                <div v-for="tip in trip.practical_tips" :key="tip" class="small muted" style="padding:2px 0">{{ tip }}</div>
              </div>
              <div v-if="trip.packing_list && trip.packing_list.length" class="packing-block">
                <h4>携带清单</h4>
                <div class="small muted">{{ trip.packing_list.join('、') }}</div>
              </div>
              <div v-if="liveAlerts.length" class="alerts-block">
                <h4>出行提醒</h4>
                <div v-for="(a, i) in liveAlerts" :key="i" class="alert-item" :class="a.level">
                  <b>{{ a.title }}</b>
                  <span class="muted"> {{ a.content }}</span>
                </div>
              </div>
              <div v-if="trip.validation_issues && trip.validation_issues.length" class="notice">
                校验提示：{{ trip.validation_issues.join('；') }}
              </div>
              <div class="notice">AI 生成的行程需管理员人工复核通过后才能发布。</div>
              <div class="action-row">
                <button class="btn sm" @click="printTrip"><i data-lucide="printer"></i> 导出 PDF</button>
                <button class="btn sm" @click="copyTrip"><i data-lucide="copy"></i> 复制攻略</button>
                <button class="btn sm" @click="downloadICS"><i data-lucide="calendar-plus"></i> 日历</button>
              </div>
            </div>
          </div>

          <div v-else-if="view==='trips'" class="card">
            <h3>我的行程</h3>
            <div v-if="trips.length===0" class="empty">还没有行程，先去规划一份</div>
            <div v-for="t in trips" :key="t.id" class="guide-item">
              <div style="display:flex;align-items:center;gap:10px">
                <b>{{ t.title }}</b>
                <span class="status" :class="t.status">{{ t.status }}</span>
              </div>
              <div class="small muted">{{ t.city }}<template v-if="t.itinerary && t.itinerary.params && t.itinerary.params.departure_date"> · {{ formatDate(t.itinerary.params.departure_date) }} - {{ formatDate(tripEndDate(t)) }}</template></div>
              <div class="guide-actions">
                <button class="btn sm" @click="openTrip(t)"><i data-lucide="eye"></i> 查看</button>
                <button class="btn sm danger" @click="deleteTrip(t)"><i data-lucide="trash-2"></i> 删除</button>
              </div>
            </div>
            <div class="pager" v-if="tripPages > 1">
              <button class="btn sm" :disabled="tripPage <= 1" @click="goTripPage(tripPage - 1)">上一页</button>
              <span class="small muted">第 {{ tripPage }} / {{ tripPages }} 页 · 共 {{ tripTotal }} 条</span>
              <button class="btn sm" :disabled="tripPage >= tripPages" @click="goTripPage(tripPage + 1)">下一页</button>
            </div>
          </div>

          <div v-else-if="view==='guides'" class="card" ref="guidesPanel">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;flex-wrap:wrap">
              <h3 style="margin:0">攻略广场</h3>
              <div style="display:flex;gap:8px">
                <button class="btn sm" @click="openMyGuidesModal"><i data-lucide="file-text"></i> 我的攻略</button>
                <button class="btn sm" @click="switchView('favorites')"><i data-lucide="heart"></i> 我的收藏</button>
                <button class="btn primary sm" @click="openGuideModal"><i data-lucide="plus"></i> 发布攻略</button>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
              <input v-model="guideCity" placeholder="城市" @keyup.enter="goGuidePage(1)" />
              <input v-model="guideKeyword" placeholder="关键词/兴趣" @keyup.enter="goGuidePage(1)" />
              <select v-model="guideSort" @change="goGuidePage(1)">
                <option value="hot">热门</option>
                <option value="new">最新</option>
              </select>
              <button class="btn sm" @click="goGuidePage(1)"><i data-lucide="filter"></i> 筛选</button>
            </div>
            <div v-if="guides.length===0" class="empty">暂无攻略</div>
            <div v-for="g in guides" :key="g.id" class="guide-item">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <b class="guide-title" @click="openGuide(g)">{{ g.title }}</b>
                <span class="tag">{{ g.city }}</span>
                <span class="small muted guide-author" @click.stop="openUserProfile(g.user_id)">
                  <img v-if="g.author_avatar" :src="g.author_avatar" class="mini-avatar" />
                  {{ g.author_nickname || g.username }}
                </span>
              </div>
              <div class="small muted" style="margin-top:6px;white-space:pre-wrap">{{ g.content }}</div>
              <div v-if="g.images && g.images.length" class="guide-images">
                <img v-for="src in g.images" :key="src" :src="src" alt="攻略图片" />
              </div>
              <div class="guide-actions">
                <button class="btn sm" @click="openGuide(g)"><i data-lucide="eye"></i> 查看详情</button>
                <button class="btn sm" :class="{primary:g.liked_by_me}" :disabled="g._likeBusy" @click="likeGuide(g)"><i data-lucide="thumbs-up"></i> {{ g.liked_by_me ? '已赞' : '点赞' }} {{ g.likes }}</button>
                <button class="btn sm" :class="{primary:g.favorited_by_me}" :disabled="g._favBusy" @click="favoriteGuide(g)"><i data-lucide="heart"></i> {{ g.favorited_by_me ? '已收藏' : '收藏' }}</button>
              </div>
            </div>
            <div class="pager" v-if="guidePages > 1">
              <button class="btn sm" :disabled="guidePage <= 1" @click="goGuidePage(guidePage - 1)">上一页</button>
              <span class="small muted">第 {{ guidePage }} / {{ guidePages }} 页 · 共 {{ guideTotal }} 条</span>
              <button class="btn sm" :disabled="guidePage >= guidePages" @click="goGuidePage(guidePage + 1)">下一页</button>
            </div>
          </div>

          <div v-if="showGuideModal" class="modal-mask" @click.self="closeGuideModal">
            <div class="modal">
              <h3>发布攻略</h3>
              <div class="field"><label>选择要发布的行程</label>
                <select v-model="guideDraft.trip_id" @change="onSelectGuideTrip">
                  <option value="">不选择行程</option>
                  <option v-for="t in trips" :key="t.id" :value="t.id">{{ t.title }}</option>
                </select>
              </div>
              <div class="field"><label>标题</label><input v-model="guideDraft.title" /></div>
              <div class="field"><label>城市</label><input v-model="guideDraft.city" :disabled="!!guideDraft.trip_id" placeholder="北京 / 成都 / 上海" /></div>
              <div class="field"><label>内容</label><textarea v-model="guideDraft.content" rows="6"></textarea></div>
              <div class="field"><label>游玩感受</label><textarea v-model="guideDraft.feelings" rows="4" placeholder="例如：最值得去的地方、哪家店最惊艳、整体体验如何"></textarea></div>
              <div class="field"><label>游玩照片（可多选）</label><input type="file" multiple accept="image/*" @change="onGuideImages" /></div>
              <div v-if="guideDraft.images && guideDraft.images.length" class="guide-images">
                <div v-for="(f, i) in guideDraft.images" :key="i" class="guide-upload-preview">
                  <img :src="f.preview" alt="图片预览" />
                  <div class="small muted">{{ f.name }}（{{ (f.size / 1024).toFixed(0) }}KB）</div>
                </div>
              </div>
              <div class="action-row">
                <button class="btn sm" @click="closeGuideModal">取消</button>
                <button class="btn primary sm" @click="createGuide" :disabled="guideSaving"><i data-lucide="plus"></i> {{ guideSaving ? "提交中..." : "提交审核" }}</button>
              </div>
            </div>
          </div>

          <div v-if="showMyGuidesModal" class="modal-mask" @click.self="closeMyGuidesModal">
            <div class="modal">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
                <h3 style="margin:0">我的攻略</h3>
                <button class="btn sm" @click="closeMyGuidesModal"><i data-lucide="x"></i> 关闭</button>
              </div>
              <div v-if="myGuides.length===0" class="empty">还没有发布过攻略</div>
              <div v-for="g in myGuides" :key="g.id" class="guide-item">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <b>{{ g.title }}</b>
                  <span class="tag">{{ g.city }}</span>
                  <span v-if="g.trip_id" class="tag">含行程</span>
                  <span class="status" :class="g.status">{{ statusText(g.status) }}</span>
                </div>
                <div class="small muted">上传时间：{{ formatDateTime(g.created_at) }}</div>
                <div class="small" style="margin-top:6px;white-space:pre-wrap">{{ g.content }}</div>
                <div v-if="g.images && g.images.length" class="guide-images">
                  <img v-for="src in g.images" :key="src" :src="src" alt="攻略图片" />
                </div>
              </div>
              <div class="pager" v-if="myGuidePages > 1">
                <button class="btn sm" :disabled="myGuidePage <= 1" @click="goMyGuidePage(myGuidePage - 1)">上一页</button>
                <span class="small muted">第 {{ myGuidePage }} / {{ myGuidePages }} 页 · 共 {{ myGuideTotal }} 条</span>
                <button class="btn sm" :disabled="myGuidePage >= myGuidePages" @click="goMyGuidePage(myGuidePage + 1)">下一页</button>
              </div>
            </div>
          </div>

          <div v-if="viewGuideModal && viewGuide" class="modal-mask guide-detail-mask" @click.self="closeGuideDetail">
            <div class="modal guide-detail-modal">
              <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">
                <div>
                  <h3 style="margin:0">{{ viewGuide.title }}</h3>
                  <div class="small muted" style="margin-top:4px">
                    <span class="guide-author" @click="openUserProfile(viewGuide.user_id)">
                      <img v-if="viewGuide.author_avatar" :src="viewGuide.author_avatar" class="mini-avatar" />
                      {{ viewGuide.author_nickname || viewGuide.username || "用户" }}
                    </span>
                    · {{ viewGuide.city }} · {{ viewGuide.created_at }}
                  </div>
                  <div v-if="viewGuide.user_id && (!profile || viewGuide.user_id !== profile.id)" style="margin-top:8px;display:flex;align-items:center;gap:10px">
                    <button class="btn sm" :class="{primary:viewGuide.is_following}" @click="toggleFollow(viewGuide)" :disabled="followSaving">
                      <i data-lucide="user-plus"></i> {{ viewGuide.is_following ? '已关注' : '关注' }}
                    </button>
                    <span class="small muted">粉丝 {{ viewGuide.followers_count || 0 }}</span>
                  </div>
                </div>
                <button class="btn sm" @click="closeGuideDetail"><i data-lucide="x"></i> 关闭</button>
              </div>
              <div v-if="viewGuide.images && viewGuide.images.length" class="guide-images guide-detail-images">
                <img v-for="src in viewGuide.images" :key="src" :src="src" alt="攻略图片" />
              </div>
              <div class="small" style="margin-top:10px;white-space:pre-wrap">{{ viewGuide.content }}</div>
              <div v-if="viewGuide.trip_itinerary && viewGuide.trip_itinerary.days && viewGuide.trip_itinerary.days.length" class="guide-trip-block" style="margin-top:12px">
                <h4 style="margin:0 0 8px">关联行程</h4>
                <div v-for="day in viewGuide.trip_itinerary.days" :key="day.day" style="padding:8px 0;border-bottom:1px dashed var(--line)">
                  <b>Day {{ day.day }} · {{ day.theme || "" }}</b>
                  <div class="small" style="margin-top:4px">景点：
                    <span v-for="a in (day.attractions || [])" :key="a.name" style="margin-right:8px">{{ a.name }} <a :href="mapLink(a)" target="_blank" rel="noopener">地图</a></span>
                    <span v-if="!day.attractions || !day.attractions.length">无</span>
                  </div>
                  <div class="small">美食：
                    <span v-for="f in (day.dining || [])" :key="f.name" style="margin-right:8px">{{ f.name }} <a :href="mapLink(f)" target="_blank" rel="noopener">地图</a></span>
                    <span v-if="!day.dining || !day.dining.length">无</span>
                  </div>
                </div>
              </div>
              <div class="guide-actions" style="margin-top:12px">
                <button v-if="viewGuide.trip_itinerary && viewGuide.trip_itinerary.days && viewGuide.trip_itinerary.days.length" class="btn primary sm" @click="copyGuideTrip"><i data-lucide="briefcase"></i> 加入我的行程</button>
                <button class="btn sm" :class="{primary:viewGuide.liked_by_me}" :disabled="viewGuide._likeBusy" @click="likeGuide(viewGuide)"><i data-lucide="thumbs-up"></i> {{ viewGuide.liked_by_me ? '已赞' : '点赞' }} {{ viewGuide.likes }}</button>
                <button class="btn sm" :class="{primary:viewGuide.favorited_by_me}" :disabled="viewGuide._favBusy" @click="favoriteGuide(viewGuide)"><i data-lucide="heart"></i> {{ viewGuide.favorited_by_me ? '已收藏' : '收藏' }}</button>
              </div>
              <div style="margin-top:14px">
                <h4>评论</h4>
                <div v-if="!viewGuide.comments || viewGuide.comments.length===0" class="small muted">还没有评论</div>
                <div v-for="cm in viewGuide.comments" :key="cm.id" class="comment-item">
                  <div class="small">{{ cm.content }}</div>
                  <div class="small muted">{{ cm.created_at }}</div>
                </div>
                <div style="display:flex;gap:8px;margin-top:10px">
                  <input v-model="guideComment" placeholder="写下你的评论" @keydown.enter.exact.prevent="addGuideComment" />
                  <button class="btn primary sm" @click="addGuideComment"><i data-lucide="send"></i> 评论</button>
                </div>
              </div>
            </div>
          </div>

          <div v-else-if="view==='favorites'" class="card">
            <h3>我的收藏</h3>
            <div class="tab-row">
              <button class="btn sm" :class="{primary: favTab==='favorited'}" @click="switchFavTab('favorited')">收藏 {{ favoriteTotal }}</button>
              <button class="btn sm" :class="{primary: favTab==='liked'}" @click="switchFavTab('liked')">点赞 {{ likedTotal }}</button>
            </div>
            <div v-if="favTab==='favorited'">
              <div v-if="favorites.length===0" class="empty">还没有收藏</div>
              <div v-for="g in favorites" :key="g.id" class="guide-item">
                <b class="guide-title" @click="openGuide(g)">{{ g.title }}</b>
                <div class="small muted">{{ g.content }}</div>
                <div v-if="g.images && g.images.length" class="guide-images">
                  <img v-for="src in g.images" :key="src" :src="src" alt="攻略图片" />
                </div>
                <div class="guide-actions">
                  <button class="btn sm" @click="openGuide(g)"><i data-lucide="eye"></i> 查看详情</button>
                </div>
              </div>
              <div class="pager" v-if="favoritePages > 1">
                <button class="btn sm" :disabled="favoritePage <= 1" @click="goFavoritePage(favoritePage - 1)">上一页</button>
                <span class="small muted">第 {{ favoritePage }} / {{ favoritePages }} 页 · 共 {{ favoriteTotal }} 条</span>
                <button class="btn sm" :disabled="favoritePage >= favoritePages" @click="goFavoritePage(favoritePage + 1)">下一页</button>
              </div>
            </div>
            <div v-else>
              <div v-if="likedGuides.length===0" class="empty">还没有点赞的攻略</div>
              <div v-for="g in likedGuides" :key="g.id" class="guide-item">
                <b class="guide-title" @click="openGuide(g)">{{ g.title }}</b>
                <div class="small muted">{{ g.content }}</div>
                <div v-if="g.images && g.images.length" class="guide-images">
                  <img v-for="src in g.images" :key="src" :src="src" alt="攻略图片" />
                </div>
                <div class="guide-actions">
                  <button class="btn sm" @click="openGuide(g)"><i data-lucide="eye"></i> 查看详情</button>
                </div>
              </div>
              <div class="pager" v-if="likedPages > 1">
                <button class="btn sm" :disabled="likedPage <= 1" @click="goLikedPage(likedPage - 1)">上一页</button>
                <span class="small muted">第 {{ likedPage }} / {{ likedPages }} 页 · 共 {{ likedTotal }} 条</span>
                <button class="btn sm" :disabled="likedPage >= likedPages" @click="goLikedPage(likedPage + 1)">下一页</button>
              </div>
            </div>
          </div>

          <div v-if="verifyPhoneModal" class="modal-mask" @click.self="verifyPhoneModal=false">
            <div class="modal">
              <h3 style="margin:0">手机号验证</h3>
              <p class="small muted" style="margin-top:8px">验证后才能生成行程和发布攻略。验证码已发送到手机；本地开发模式见服务端日志。</p>
              <div class="field">
                <label>验证码</label>
                <div style="display:flex;gap:8px">
                  <input v-model="verifyPhoneCode" placeholder="6 位验证码" />
                  <button class="btn sm" @click="sendVerifyPhoneCode" :disabled="codeSending">{{ codeSending ? '发送中' : '获取验证码' }}</button>
                </div>
              </div>
              <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
              <div class="action-row">
                <button class="btn sm" @click="verifyPhoneModal=false">稍后</button>
                <button class="btn primary sm" @click="verifyPhone">验证</button>
              </div>
            </div>
          </div>

          <div v-if="securityModal" class="modal-mask" @click.self="!forcePasswordChange && closeSecurityModal()">
            <div class="modal">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
                <h3 style="margin:0">账号安全</h3>
                <button class="btn sm" v-if="!forcePasswordChange" @click="closeSecurityModal"><i data-lucide="x"></i> 关闭</button>
              </div>
              <div style="display:flex;gap:8px;margin:12px 0">
                <button class="btn sm" :class="{primary: securityTab==='password'}" @click="securityTab='password'">修改密码</button>
                <button class="btn sm" :class="{primary: securityTab==='2fa'}" @click="securityTab='2fa'">动态口令</button>
              </div>

              <div v-if="securityTab==='password'">
                <p v-if="forcePasswordChange" class="small" style="margin:6px 0;color:#c0392b">首次登录请先修改默认密码</p>
                <div class="field"><label>原密码</label><input v-model="changeOldPassword" type="password" /></div>
                <div class="field"><label>新密码（8 位以上，含字母和数字）</label><input v-model="changeNewPassword" type="password" /></div>
                <div class="field"><label>确认新密码</label><input v-model="changeConfirmPassword" type="password" /></div>
                <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
                <button class="btn primary block" @click="changePassword">保存新密码</button>
              </div>

              <div v-else-if="securityTab==='2fa' && !(profile && profile.totp_enabled)">
                <p class="small muted">开启后登录需要额外输入动态验证码。</p>
                <button class="btn primary block" @click="setup2fa">开启动态口令</button>
              </div>

              <div v-else-if="securityTab==='2fa_setup'">
                <p class="small muted">在 Authenticator / 微信小程序等工具中扫描或手动输入密钥：</p>
                <div class="field"><label>密钥</label><input :value="pendingTotpSecret" readonly /></div>
                <div class="field"><label>动态验证码</label><input v-model="totpSetupCode" /></div>
                <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
                <button class="btn primary block" @click="enable2fa">确认并开启</button>
              </div>

              <div v-else>
                <p class="small muted">当前已开启动态口令，输入验证码后可关闭。</p>
                <div class="field"><label>动态验证码</label><input v-model="totpDisableCode" /></div>
                <p v-if="authError" class="small" style="margin:6px 0;color:#c0392b">{{ authError }}</p>
                <button class="btn block" @click="disable2fa">关闭动态口令</button>
              </div>
            </div>
          </div>

          <div v-if="profileModal && profile" class="modal-mask" @click.self="closeProfileModal">
            <div class="modal">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
                <h3 style="margin:0">个人主页</h3>
                <button class="btn sm" @click="closeProfileModal"><i data-lucide="x"></i> 关闭</button>
              </div>
              <div style="display:flex;align-items:center;gap:14px;margin:14px 0">
                <img v-if="profileAvatarPreview || profileDraft.avatar" :src="profileAvatarPreview || profileDraft.avatar" class="profile-avatar" alt="头像" />
                <div v-else class="profile-avatar profile-avatar-empty"><i data-lucide="user"></i></div>
                <div>
                  <div class="small muted">关注 {{ profile.following_count || 0 }} · 粉丝 {{ profile.followers_count || 0 }}</div>
                </div>
              </div>
              <div class="field"><label>昵称</label><input v-model="profileDraft.nickname" maxlength="40" /></div>
              <div class="field"><label>头像</label><input type="file" accept="image/*" @change="onProfileAvatar" /></div>
              <div class="action-row">
                <button class="btn sm" @click="closeProfileModal">取消</button>
                <button class="btn primary sm" @click="saveProfile"><i data-lucide="save"></i> 保存</button>
              </div>
            </div>
          </div>

          <div v-if="userProfileModal && viewUserProfile" class="modal-mask" @click.self="closeUserProfile">
            <div class="modal">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
                <h3 style="margin:0">{{ viewUserProfile.nickname || viewUserProfile.username }}</h3>
                <button class="btn sm" @click="closeUserProfile"><i data-lucide="x"></i> 关闭</button>
              </div>
              <div style="display:flex;align-items:center;gap:14px;margin:14px 0">
                <img v-if="viewUserProfile.avatar" :src="viewUserProfile.avatar" class="profile-avatar" alt="头像" />
                <div v-else class="profile-avatar profile-avatar-empty"><i data-lucide="user"></i></div>
                <div>
                  <div class="small muted">@{{ viewUserProfile.username }}</div>
                  <div class="small muted">关注 {{ viewUserProfile.following_count || 0 }} · 粉丝 {{ viewUserProfile.followers_count || 0 }}</div>
                  <div v-if="viewUserProfile.id !== (profile && profile.id)" style="margin-top:8px">
                    <button class="btn sm" :class="{primary:viewUserProfile.is_following}" @click="toggleFollow(viewUserProfile)" :disabled="followSaving">
                      <i data-lucide="user-plus"></i> {{ viewUserProfile.is_following ? '已关注' : '关注' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-else-if="view==='metrics'" class="card">
            <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
              <h3 style="margin:0">运行时指标</h3>
              <button class="btn sm" @click="loadMetrics"><i data-lucide="refresh-cw"></i> 刷新</button>
              <button class="btn sm" @click="runEval"><i data-lucide="flask-conical"></i> 运行评测</button>
            </div>
            <div v-if="metrics" class="metric-row">
              <div class="metric"><div class="label">请求成功率</div><div class="value">{{ (metrics.success_rate*100).toFixed(1) }}%</div></div>
              <div class="metric"><div class="label">P95 延迟</div><div class="value">{{ metrics.p95_latency_ms }}ms</div></div>
              <div class="metric"><div class="label">失败类型</div><div class="value">{{ Object.keys(metrics.failure_types||{}).length }}</div></div>
            </div>
            <pre v-if="metrics" class="small">{{ JSON.stringify(metrics, null, 2) }}</pre>
            <div v-if="agentRuns && agentRuns.length">
              <h4 style="margin:14px 0 8px">运行记录</h4>
              <table class="table">
                <tr><th>run_id</th><th>意图</th><th>状态</th><th>Token</th><th>耗时</th><th>时间</th></tr>
                <tr v-for="r in agentRuns" :key="r.run_id">
                  <td class="small">{{ r.run_id }}</td>
                  <td>{{ r.intent }}</td>
                  <td>{{ r.status }}</td>
                  <td>{{ (r.prompt_tokens || 0) + (r.completion_tokens || 0) }}</td>
                  <td>{{ r.latency_ms }}ms</td>
                  <td class="small">{{ formatDateTime(r.created_at) }}</td>
                </tr>
              </table>
            </div>
            <div v-if="evalReport">
              <h4>评测结果</h4>
              <div class="metric-row">
                <div class="metric"><div class="label">用例数</div><div class="value">{{ evalReport.total }}</div></div>
                <div class="metric"><div class="label">通过率</div><div class="value">{{ (evalReport.pass_rate*100).toFixed(1) }}%</div></div>
                <div class="metric"><div class="label">失败类型</div><div class="value">{{ Object.keys(evalReport.failure_types||{}).length }}</div></div>
              </div>
              <pre class="small">{{ JSON.stringify(evalReport.failure_types, null, 2) }}</pre>
            </div>
          </div>

          <div v-else-if="view==='admin' && isAdmin" class="grid">
            <div class="card" style="grid-column: 1 / -1">
              <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
                <button class="btn sm" :class="{primary:adminTab==='reviews'}" @click="adminTab='reviews'">人工复核</button>
                <button class="btn sm" :class="{primary:adminTab==='users'}" @click="adminTab='users'">用户治理</button>
                <button class="btn sm" :class="{primary:adminTab==='audit'}" @click="adminTab='audit'">审计日志</button>
                <button class="btn sm" :class="{primary:adminTab==='prices'}" @click="adminTab='prices'">真实数据</button>
              </div>
              <div v-if="adminTab==='reviews'">
                <table class="table">
                  <tr><th>类型</th><th>摘要</th><th>状态</th><th>操作</th></tr>
                  <tr v-for="r in reviews" :key="r.id">
                    <td>{{ r.target_type === 'guide' ? '攻略' : r.target_type === 'trip' ? '行程' : r.target_type }}</td>
                    <td>{{ r.summary }}</td>
                    <td><span class="status" :class="r.status">{{ statusText(r.status) }}</span></td>
                    <td>
                      <button v-if="r.status==='pending'" class="btn sm" @click="decideReview(r,'approved')">通过</button>
                      <button v-if="r.status==='pending'" class="btn sm danger" @click="decideReview(r,'rejected')">驳回</button>
                    </td>
                  </tr>
                </table>
              </div>
              <div v-if="adminTab==='users'">
                <table class="table">
                  <tr><th>用户</th><th>角色</th><th>状态</th><th>操作</th></tr>
                  <tr v-for="u in users" :key="u.id">
                    <td>{{ u.username }}</td><td>{{ u.role }}</td><td>{{ u.status }}</td>
                    <td>
                      <button class="btn sm" @click="setUserStatus(u,'muted')">禁言</button>
                      <button class="btn sm danger" @click="setUserStatus(u,'banned')">封禁</button>
                      <button class="btn sm" @click="setUserStatus(u,'active')">解封</button>
                    </td>
                  </tr>
                </table>
              </div>
              <div v-if="adminTab==='audit'">
                <table class="table">
                  <tr><th>时间</th><th>动作</th><th>对象</th><th>详情</th></tr>
                  <tr v-for="a in auditLogs" :key="a.id">
                    <td>{{ a.created_at }}</td><td>{{ a.action }}</td><td>{{ a.target_type }} {{ a.target_id }}</td><td>{{ a.detail }}</td>
                  </tr>
                </table>
              </div>
              <div v-if="adminTab==='prices'">
                <h4 style="margin:0 0 8px">价格库</h4>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:10px">
                  <input v-model="priceDraft.place_name" placeholder="地点/店名" />
                  <input v-model="priceDraft.city" placeholder="城市" />
                  <input v-model="priceDraft.price" type="number" placeholder="价格" />
                  <input v-model="priceDraft.source" placeholder="来源" />
                  <input v-model="priceDraft.source_url" placeholder="来源链接" />
                  <input v-model="priceDraft.note" placeholder="备注" />
                </div>
                <button class="btn primary sm" @click="savePrice"><i data-lucide="save"></i> 保存价格</button>
                <table class="table" style="margin-top:10px">
                  <tr><th>地点</th><th>城市</th><th>价格</th><th>来源</th><th>更新时间</th><th>操作</th></tr>
                  <tr v-for="p in priceReferences" :key="p.id">
                    <td>{{ p.place_name }}</td><td>{{ p.city }}</td><td>¥{{ p.price }}</td><td>{{ p.source }}</td><td>{{ formatDateTime(p.updated_at) }}</td>
                    <td><button class="btn sm danger" @click="deletePrice(p.id)">删除</button></td>
                  </tr>
                </table>
                <h4 style="margin:16px 0 8px">用户价格反馈</h4>
                <table class="table">
                  <tr><th>地点</th><th>城市</th><th>反馈价</th><th>状态</th><th>操作</th></tr>
                  <tr v-for="f in priceFeedback" :key="f.id">
                    <td>{{ f.place_name }}</td><td>{{ f.city }}</td><td>¥{{ f.price }}</td><td>{{ statusText(f.status) }}</td>
                    <td>
                      <button v-if="f.status==='pending'" class="btn sm" @click="decidePriceFeedback(f,'approved')">采用</button>
                      <button v-if="f.status==='pending'" class="btn sm danger" @click="decidePriceFeedback(f,'rejected')">驳回</button>
                    </td>
                  </tr>
                </table>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  `,
}).mount("#app");

