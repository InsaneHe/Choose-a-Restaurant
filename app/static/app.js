const listElement = document.querySelector("#restaurants");
const countElement = document.querySelector("#count");
const archiveListElement = document.querySelector("#archived-restaurants");
const archiveCountElement = document.querySelector("#archive-count");
const feedbackElement = document.querySelector("#feedback");
const formElement = document.querySelector("#restaurant-form");
const editorHeading = document.querySelector("#editor-heading");
const idInput = document.querySelector("#restaurant-id");
const nameInput = document.querySelector("#name");
const typeInput = document.querySelector("#type");
const detailInput = document.querySelector("#detail");
const tagInput = document.querySelector("#tag-input");
const addTagButton = document.querySelector("#add-tag-button");
const tagEditor = document.querySelector("#tag-editor");
const dianpingShareInput = document.querySelector("#dianping-share-input");
const parseDianpingButton = document.querySelector("#parse-dianping-button");
const dianpingPreview = document.querySelector("#dianping-preview");
const dianpingPreviewName = document.querySelector("#dianping-preview-name");
const dianpingPreviewUrl = document.querySelector("#dianping-preview-url");
const dianpingPreviewAddress = document.querySelector("#dianping-preview-address");
const useDianpingButton = document.querySelector("#use-dianping-button");
const dianpingUrlInput = document.querySelector("#dianping-url");
const saveButton = document.querySelector("#save-button");
const cancelButton = document.querySelector("#cancel-button");
const randomButton = document.querySelector("#random-button");
const randomResult = document.querySelector("#random-result");
const randomNumber = document.querySelector("#random-number");
const randomTotal = document.querySelector("#random-total");
const randomName = document.querySelector("#random-name");
const randomType = document.querySelector("#random-type");
const resolveAllButton = document.querySelector("#resolve-all-button");
const mapStatus = document.querySelector("#map-status");
const mapContainer = document.querySelector("#map-container");
const mapPlaceholder = document.querySelector("#map-placeholder");
const batchResults = document.querySelector("#batch-results");
const locationPanelHeading = document.querySelector("#location-panel-heading");
const locationHint = document.querySelector("#location-hint");
const placeSearchForm = document.querySelector("#place-search-form");
const placeQuery = document.querySelector("#place-query");
const placeCandidates = document.querySelector("#place-candidates");
const manualLocationForm = document.querySelector("#manual-location-form");
const locationAddress = document.querySelector("#location-address");
const locationLongitude = document.querySelector("#location-longitude");
const locationLatitude = document.querySelector("#location-latitude");
const locationPoiId = document.querySelector("#location-poi-id");
const nearbyTransit = document.querySelector("#nearby-transit");
const participantsElement = document.querySelector("#participants");
const addParticipantButton = document.querySelector("#add-participant-button");
const rankButton = document.querySelector("#rank-button");
const groupRandomButton = document.querySelector("#group-random-button");
const groupStatus = document.querySelector("#group-status");
const groupResults = document.querySelector("#group-results");
const rankingList = document.querySelector("#ranking-list");
const excludedList = document.querySelector("#excluded-list");
const groupRandomResult = document.querySelector("#group-random-result");
const runtimeMode = document.querySelector("#runtime-mode");
const runtimeDataPath = document.querySelector("#runtime-data-path");
const openDataDirectoryButton = document.querySelector("#open-data-directory-button");
const restaurantImportFile = document.querySelector("#restaurant-import-file");
const importRestaurantsButton = document.querySelector("#import-restaurants-button");
const importStatus = document.querySelector("#import-status");
const amapSettingsForm = document.querySelector("#amap-settings-form");
const amapWebKey = document.querySelector("#amap-web-key");
const amapJsKey = document.querySelector("#amap-js-key");
const amapSecurityKey = document.querySelector("#amap-security-key");
const amapSettingsStatus = document.querySelector("#amap-settings-status");

let restaurantsCache = [];
let activeRestaurant = null;
let amapApi = null;
let mapInstance = null;
let mapMarkers = [];
let participantCounter = 0;
let latestGroupRankingId = null;
let hasGroupRankingAttempt = false;
let eligibilitySignature = null;
let editingTags = [];
let parsedDianpingResult = null;
let dianpingShareAccepted = false;

function setFeedback(message, kind = "success") {
  feedbackElement.textContent = message;
  feedbackElement.className = `feedback ${kind}`;
  feedbackElement.hidden = false;
}

function clearFeedback() {
  feedbackElement.hidden = true;
  feedbackElement.textContent = "";
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

async function loadRuntimeInfo() {
  try {
    const info = await apiRequest("/api/runtime/info");
    runtimeMode.textContent =
      info.mode === "packaged"
        ? "发行包模式：名单保存在当前 Windows 用户目录，替换程序不会覆盖。"
        : "源码开发模式：名单继续使用项目 data/restaurants.json。";
    runtimeDataPath.textContent = info.data_path;
  } catch (error) {
    runtimeMode.textContent = `无法读取运行信息：${error.message}`;
  }
}

async function loadAmapSettingsStatus() {
  try {
    const status = await apiRequest("/api/settings/amap");
    const storageLabel =
      status.storage === "windows_current_user"
        ? "Windows 当前用户保护存储"
        : "开发环境变量";
    amapSettingsStatus.textContent = `${storageLabel}；Web 服务：${
      status.web_service_configured ? "已配置" : "未配置"
    }；JS API：${status.js_api_configured ? "已配置" : "未配置"}；安全密钥：${
      status.js_security_configured ? "已配置" : "未配置"
    }。`;
  } catch (error) {
    amapSettingsStatus.textContent = `配置状态读取失败：${error.message}`;
  }
}

function appendText(parent, className, text) {
  const element = document.createElement("p");
  element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function locationLabel(status) {
  if (status === "auto_resolved") {
    return "自动匹配";
  }
  if (status === "manual_confirmed") {
    return "人工确认";
  }
  return "待定位";
}

function secondsLabel(seconds) {
  return `${Math.max(1, Math.round(seconds / 60))} 分钟`;
}

function invalidateGroupRanking(message, { keepAttempt = false } = {}) {
  latestGroupRankingId = null;
  groupRandomButton.disabled = true;
  groupRandomResult.hidden = true;
  groupResults.hidden = true;
  rankingList.replaceChildren();
  excludedList.replaceChildren();
  if (!keepAttempt) {
    hasGroupRankingAttempt = false;
  }
  if (message) {
    groupStatus.textContent = message;
  }
}

function selectRestaurantForLocation(restaurant) {
  activeRestaurant = restaurant;
  locationPanelHeading.textContent = `定位 #${restaurant.id} ${restaurant.name}`;
  locationHint.textContent =
    restaurant.location_status === "pending_location"
      ? "搜索只返回上海高德候选；不确定时请人工选择，不会自动采用第一条。"
      : `当前位置来源：${locationLabel(restaurant.location_status)}。可重新搜索并人工更正。`;
  placeSearchForm.hidden = false;
  manualLocationForm.hidden = false;
  placeQuery.value = restaurant.name;
  locationAddress.value = restaurant.address || "";
  locationLongitude.value = restaurant.longitude ?? "";
  locationLatitude.value = restaurant.latitude ?? "";
  locationPoiId.value = restaurant.amap_poi_id || "";
  placeCandidates.replaceChildren();
  nearbyTransit.replaceChildren();
  document.querySelector(".map-section").scrollIntoView({ behavior: "smooth" });
}

function renderTagEditor() {
  tagEditor.replaceChildren();
  for (const tag of editingTags) {
    const chip = document.createElement("span");
    chip.className = "tag-chip editable";
    const label = document.createElement("span");
    label.textContent = tag;
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "tag-remove";
    removeButton.textContent = "×";
    removeButton.setAttribute("aria-label", `移除标签 ${tag}`);
    removeButton.addEventListener("click", () => {
      editingTags = editingTags.filter((item) => item !== tag);
      renderTagEditor();
    });
    chip.append(label, removeButton);
    tagEditor.append(chip);
  }
}

function addPendingTag({ showEmptyError = true } = {}) {
  const tag = tagInput.value.trim();
  if (!tag) {
    if (showEmptyError) {
      setFeedback("标签不能为空。", "error");
    }
    return false;
  }
  if (!editingTags.includes(tag)) {
    editingTags.push(tag);
  }
  tagInput.value = "";
  renderTagEditor();
  return true;
}

function clearDianpingPreview() {
  parsedDianpingResult = null;
  dianpingShareAccepted = false;
  dianpingPreview.hidden = true;
  dianpingPreviewName.textContent = "";
  dianpingPreviewUrl.textContent = "";
  dianpingPreviewAddress.textContent = "";
}

function renderDianpingPreview(result) {
  parsedDianpingResult = result;
  dianpingShareAccepted = false;
  dianpingPreviewName.textContent = result.name_suggestion || "未能可信提取，请手工填写";
  dianpingPreviewUrl.textContent = result.url;
  dianpingPreviewAddress.textContent = result.address_hint || "未提取到明确地址线索";
  dianpingPreview.hidden = false;
}

function resetEditor() {
  formElement.reset();
  editingTags = [];
  renderTagEditor();
  clearDianpingPreview();
  idInput.value = "";
  editorHeading.textContent = "添加餐厅";
  saveButton.textContent = "添加到名单";
  cancelButton.hidden = true;
}

function beginEdit(restaurant) {
  clearDianpingPreview();
  dianpingShareInput.value = "";
  idInput.value = String(restaurant.id);
  nameInput.value = restaurant.name;
  typeInput.value = restaurant.type;
  detailInput.value = restaurant.detail;
  editingTags = [...(restaurant.tags || [])];
  renderTagEditor();
  dianpingUrlInput.value = restaurant.dianping_url || "";
  editorHeading.textContent = `编辑 #${restaurant.id}`;
  saveButton.textContent = "保存修改";
  cancelButton.hidden = false;
  document.querySelector(".editor-panel").scrollIntoView({ behavior: "smooth" });
  nameInput.focus();
}

async function removeRestaurant(restaurant) {
  if (!window.confirm(`确定删除“${restaurant.name}”吗？`)) {
    return;
  }
  try {
    await apiRequest(`/api/restaurants/${restaurant.id}`, { method: "DELETE" });
    if (idInput.value === String(restaurant.id)) {
      resetEditor();
    }
    randomResult.hidden = true;
    invalidateGroupRanking("餐厅名单已变化，旧多人排名已失效。 ");
    await loadRestaurants();
    setFeedback(`已删除“${restaurant.name}”。`);
  } catch (error) {
    setFeedback(error.message, "error");
  }
}

async function changeSelectionStatus(restaurant, selectionStatus) {
  const archiving = selectionStatus === "archived";
  const action = archiving ? "归档" : "恢复";
  if (archiving && !window.confirm(`确定归档“${restaurant.name}”吗？`)) {
    return;
  }
  const shouldRerank = hasGroupRankingAttempt;
  try {
    const saved = await apiRequest(
      `/api/restaurants/${restaurant.id}/selection-status`,
      {
        method: "PATCH",
        body: JSON.stringify({ selection_status: selectionStatus }),
      },
    );
    randomResult.hidden = true;
    invalidateGroupRanking(
      archiving
        ? "餐厅已归档，旧多人排名已失效。"
        : "餐厅已恢复，旧多人排名已失效。",
      { keepAttempt: shouldRerank },
    );
    if (activeRestaurant?.id === restaurant.id) {
      activeRestaurant = saved;
    }
    await loadRestaurants();
    if (shouldRerank) {
      setFeedback(`已${action}“${restaurant.name}”，正在使用原参与者重新排名。`);
      await runGroupRanking();
    } else {
      setFeedback(`已${action}“${restaurant.name}”。`);
    }
  } catch (error) {
    setFeedback(error.message, "error");
  }
}

function renderRestaurantCards(target, restaurants, archived) {
  target.replaceChildren();
  if (restaurants.length === 0) {
    appendText(
      target,
      "empty-state",
      archived
        ? "档案为空。归档后的餐厅会出现在这里。"
        : "当前没有可选择的餐厅；单人随机和多人排名均不可用，可从档案恢复餐厅。",
    );
    return;
  }

  for (const restaurant of restaurants) {
    const card = document.createElement("article");
    card.className = archived ? "restaurant-card archived" : "restaurant-card";

    const number = document.createElement("span");
    number.className = "restaurant-id";
    number.textContent = String(restaurant.id).padStart(2, "0");
    card.append(number);

    const name = document.createElement("h3");
    name.textContent = restaurant.name;
    card.append(name);

    appendText(card, "restaurant-type", restaurant.type);
    appendText(card, "restaurant-detail", restaurant.detail);

    if (restaurant.tags.length > 0) {
      const tags = document.createElement("div");
      tags.className = "restaurant-tags";
      for (const tag of restaurant.tags) {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        chip.textContent = tag;
        tags.append(chip);
      }
      card.append(tags);
    }

    if (archived) {
      appendText(card, "archive-badge", "已归档 · 不参与随机与多人排名");
    }

    const locationBadge = document.createElement("span");
    locationBadge.className = `location-badge ${restaurant.location_status}`;
    locationBadge.textContent = locationLabel(restaurant.location_status);
    card.append(locationBadge);
    if (restaurant.address) {
      appendText(card, "restaurant-address", restaurant.address);
    }

    if (restaurant.dianping_url) {
      const link = document.createElement("a");
      link.className = "restaurant-link";
      link.href = restaurant.dianping_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer nofollow";
      link.textContent = "大众点评链接";
      card.append(link);
    }

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const locationButton = document.createElement("button");
    locationButton.className = "text-button";
    locationButton.type = "button";
    locationButton.textContent =
      restaurant.location_status === "pending_location" ? "定位" : "更正位置";
    locationButton.addEventListener("click", () =>
      selectRestaurantForLocation(restaurant),
    );
    const editButton = document.createElement("button");
    editButton.className = "text-button";
    editButton.type = "button";
    editButton.textContent = "编辑";
    editButton.addEventListener("click", () => beginEdit(restaurant));
    const deleteButton = document.createElement("button");
    deleteButton.className = "text-button danger";
    deleteButton.type = "button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => removeRestaurant(restaurant));
    const statusButton = document.createElement("button");
    statusButton.className = "text-button";
    statusButton.type = "button";
    statusButton.textContent = archived ? "恢复" : "归档";
    statusButton.addEventListener("click", () =>
      changeSelectionStatus(restaurant, archived ? "active" : "archived"),
    );
    actions.append(locationButton);
    if (restaurant.location_status !== "pending_location") {
      const nearbyButton = document.createElement("button");
      nearbyButton.className = "text-button";
      nearbyButton.type = "button";
      nearbyButton.textContent = "附近交通";
      nearbyButton.addEventListener("click", () => {
        selectRestaurantForLocation(restaurant);
        loadNearbyTransit(restaurant);
      });
      actions.append(nearbyButton);
    }
    actions.append(editButton, statusButton, deleteButton);
    card.append(actions);
    target.append(card);
  }
}

function renderRestaurants(restaurants) {
  restaurantsCache = restaurants;
  const active = restaurants.filter(
    (restaurant) => restaurant.selection_status !== "archived",
  );
  const archived = restaurants.filter(
    (restaurant) => restaurant.selection_status === "archived",
  );
  countElement.textContent = `${active.length} 家`;
  archiveCountElement.textContent = `${archived.length} 家`;
  randomButton.disabled = active.length === 0;
  renderRestaurantCards(listElement, active, false);
  renderRestaurantCards(archiveListElement, archived, true);
  refreshMapMarkers();
}

async function loadRestaurants() {
  try {
    const restaurants = await apiRequest("/api/restaurants");
    const currentSignature = restaurants
      .map((restaurant) => `${restaurant.id}:${restaurant.selection_status}`)
      .join("|");
    if (
      eligibilitySignature !== null &&
      eligibilitySignature !== currentSignature &&
      latestGroupRankingId !== null
    ) {
      invalidateGroupRanking(
        "餐厅活跃状态已在文件中变化，旧多人排名已失效，请重新计算。",
      );
    }
    eligibilitySignature = currentSignature;
    renderRestaurants(restaurants);
  } catch (error) {
    listElement.replaceChildren();
    countElement.textContent = "读取失败";
    setFeedback(error.message, "error");
  }
}

function loadAmapScript(key, serviceHost) {
  return new Promise((resolve, reject) => {
    window._AMapSecurityConfig = {
      serviceHost: `${window.location.origin}${serviceHost}`,
    };
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
    script.async = true;
    script.addEventListener("load", () => resolve(window.AMap));
    script.addEventListener("error", () => reject(new Error("高德地图 JS API 加载失败")));
    document.head.append(script);
  });
}

async function loadMapConfiguration() {
  try {
    const config = await apiRequest("/api/map/config");
    resolveAllButton.disabled = !config.web_service_enabled;
    if (!config.web_service_enabled) {
      resolveAllButton.title = "未配置高德 Web 服务密钥";
    }
    if (!config.js_api_enabled) {
      mapStatus.textContent = config.web_service_enabled
        ? "缺少高德 JS API 安全代理配置；地点搜索可用，但地图暂不可用。"
        : "缺少高德 Web 服务及 JS API 安全代理配置；名单管理和随机选择仍可使用。";
      mapPlaceholder.textContent = "地图配置缺失，未尝试加载高德地图";
      return;
    }

    amapApi = await loadAmapScript(config.js_api_key, config.service_host);
    mapContainer.replaceChildren();
    mapInstance = new amapApi.Map(mapContainer, {
      viewMode: "2D",
      zoom: 11,
      center: [121.4737, 31.2304],
      mapStyle: "amap://styles/whitesmoke",
    });
    mapInstance.on("click", (event) => {
      if (!activeRestaurant) {
        setFeedback("请先从餐厅名单选择一家进行定位。", "error");
        return;
      }
      locationLongitude.value = event.lnglat.getLng().toFixed(6);
      locationLatitude.value = event.lnglat.getLat().toFixed(6);
      locationPoiId.value = "";
      locationHint.textContent = "已选择地图点，请填写可核对的地址后保存人工确认位置。";
    });
    mapStatus.textContent = "上海地图已加载；只显示已有有效坐标的已确认门店。";
    refreshMapMarkers();
  } catch (error) {
    mapStatus.textContent = `地图加载失败：${error.message}。名单管理和随机选择仍可使用。`;
    mapPlaceholder.textContent = "地图加载失败";
  }
}

function refreshMapMarkers() {
  if (!mapInstance || !amapApi) {
    return;
  }
  if (mapMarkers.length > 0) {
    mapInstance.remove(mapMarkers);
  }
  mapMarkers = [];
  const located = restaurantsCache.filter(
    (restaurant) =>
      ["auto_resolved", "manual_confirmed"].includes(restaurant.location_status) &&
      Number.isFinite(restaurant.longitude) &&
      Number.isFinite(restaurant.latitude),
  );

  for (const restaurant of located) {
    const marker = new amapApi.Marker({
      position: [restaurant.longitude, restaurant.latitude],
      title: restaurant.name,
    });
    marker.on("click", () => {
      const content = document.createElement("div");
      content.className = "map-info";
      const heading = document.createElement("strong");
      heading.textContent = restaurant.name;
      content.append(heading);
      appendText(content, "", restaurant.address || "地址未提供");
      appendText(content, "", `定位来源：${locationLabel(restaurant.location_status)}`);
      const infoWindow = new amapApi.InfoWindow({ content, offset: new amapApi.Pixel(0, -28) });
      infoWindow.open(mapInstance, [restaurant.longitude, restaurant.latitude]);
      selectRestaurantForLocation(restaurant);
      loadNearbyTransit(restaurant);
    });
    marker.setMap(mapInstance);
    mapMarkers.push(marker);
  }
  if (mapMarkers.length > 0) {
    mapInstance.setFitView(mapMarkers, false, [50, 50, 50, 50], 15);
  }
}

function choosePlaceCandidate(candidate) {
  locationAddress.value = candidate.address || "";
  locationLongitude.value = candidate.longitude ?? "";
  locationLatitude.value = candidate.latitude ?? "";
  locationPoiId.value = candidate.poi_id;
  locationHint.textContent = "已选择高德候选，请核对名称、区域、地址和地图点后保存。";
  if (mapInstance && candidate.longitude !== null && candidate.latitude !== null) {
    mapInstance.setCenter([candidate.longitude, candidate.latitude]);
    mapInstance.setZoom(16);
  }
}

function renderPlaceCandidates(result) {
  placeCandidates.replaceChildren();
  if (result.candidates.length === 0) {
    appendText(placeCandidates, "empty-state compact", "未找到上海门店候选；可修改关键词或在地图点选并填写地址。 ");
    return;
  }

  appendText(
    placeCandidates,
    "candidate-summary",
    result.auto_eligible
      ? "找到唯一标准化精确候选；仍请核对后人工确认。"
      : `找到 ${result.candidates.length} 个候选；模糊结果或多分店不会自动选择。`,
  );
  for (const candidate of result.candidates) {
    const card = document.createElement("article");
    card.className = "candidate-card";
    const name = document.createElement("strong");
    name.textContent = candidate.name;
    card.append(name);
    appendText(
      card,
      "",
      [candidate.district, candidate.address].filter(Boolean).join(" · ") || "地址不完整",
    );
    appendText(card, "candidate-id", `POI ID：${candidate.poi_id}`);
    const selectButton = document.createElement("button");
    selectButton.className = "button quiet";
    selectButton.type = "button";
    selectButton.textContent = "选择此门店";
    selectButton.disabled =
      !candidate.address || candidate.longitude === null || candidate.latitude === null;
    selectButton.addEventListener("click", () => choosePlaceCandidate(candidate));
    card.append(selectButton);
    placeCandidates.append(card);
  }
}

async function loadNearbyTransit(restaurant) {
  nearbyTransit.replaceChildren();
  appendText(nearbyTransit, "candidate-summary", "正在查询约 1 公里内的公交/地铁站…");
  try {
    const result = await apiRequest(`/api/restaurants/${restaurant.id}/nearby-transit`);
    nearbyTransit.replaceChildren();
    const title = document.createElement("h4");
    title.textContent = `${restaurant.name} · 附近交通`;
    nearbyTransit.append(title);
    if (result.stations.length === 0) {
      appendText(nearbyTransit, "empty-state compact", "约 1 公里内未查到公交或地铁站。 ");
      return;
    }
    appendText(nearbyTransit, "field-help", result.distance_note);
    for (const station of result.stations) {
      appendText(
        nearbyTransit,
        "station-item",
        `${station.category} · ${station.name} · 约 ${station.distance_m} 米`,
      );
    }
  } catch (error) {
    nearbyTransit.replaceChildren();
    appendText(nearbyTransit, "error-text", `附近站点查询失败：${error.message}`);
  }
}

function updateParticipantRemoveButtons() {
  const cards = [...participantsElement.querySelectorAll(".participant-card")];
  for (const card of cards) {
    card.querySelector(".remove-participant").disabled = cards.length <= 2;
  }
}

function clearConfirmedOrigin(card, message = "尚未确认出发地") {
  delete card.dataset.address;
  delete card.dataset.longitude;
  delete card.dataset.latitude;
  delete card.dataset.poiId;
  card.dataset.confirmed = "false";
  const confirmation = card.querySelector(".origin-confirmation");
  confirmation.textContent = message;
  confirmation.className = "origin-confirmation pending";
}

function confirmOrigin(card, candidate) {
  card.dataset.address = candidate.address;
  card.dataset.longitude = String(candidate.longitude);
  card.dataset.latitude = String(candidate.latitude);
  card.dataset.poiId = candidate.poi_id;
  card.dataset.confirmed = "true";
  const confirmation = card.querySelector(".origin-confirmation");
  confirmation.textContent = `已确认：${candidate.name} · ${candidate.district || "上海"} · ${candidate.address}`;
  confirmation.className = "origin-confirmation confirmed";
  card.querySelector(".origin-candidates").replaceChildren();
  invalidateGroupRanking("参与者出发地已变化，请重新计算排名。 ");
}

function renderOriginCandidates(card, candidates) {
  const container = card.querySelector(".origin-candidates");
  container.replaceChildren();
  if (candidates.length === 0) {
    appendText(container, "error-text", "没有找到上海出发地候选，请换一个更具体的关键词。 ");
    return;
  }
  for (const candidate of candidates) {
    const item = document.createElement("div");
    item.className = "origin-candidate";
    const description = document.createElement("span");
    description.textContent = [candidate.name, candidate.district, candidate.address]
      .filter(Boolean)
      .join(" · ");
    const chooseButton = document.createElement("button");
    chooseButton.type = "button";
    chooseButton.className = "text-button";
    chooseButton.textContent = "确认此出发点";
    chooseButton.disabled =
      !candidate.address || candidate.longitude === null || candidate.latitude === null;
    chooseButton.addEventListener("click", () => confirmOrigin(card, candidate));
    item.append(description, chooseButton);
    container.append(item);
  }
}

async function searchParticipantOrigin(card) {
  const queryInput = card.querySelector(".origin-query");
  const query = queryInput.value.trim();
  const container = card.querySelector(".origin-candidates");
  if (!query) {
    clearConfirmedOrigin(card, "请先填写上海出发地关键词");
    queryInput.focus();
    return;
  }
  container.replaceChildren();
  appendText(container, "candidate-summary", "正在搜索上海地点…");
  try {
    const result = await apiRequest(`/api/origins/search?q=${encodeURIComponent(query)}`);
    renderOriginCandidates(card, result.candidates);
  } catch (error) {
    container.replaceChildren();
    appendText(container, "error-text", `出发地搜索失败：${error.message}`);
  }
}

function addParticipant() {
  participantCounter += 1;
  const participantId = `participant-${participantCounter}`;
  const card = document.createElement("article");
  card.className = "participant-card";
  card.dataset.participantId = participantId;
  card.dataset.confirmed = "false";

  const headingRow = document.createElement("div");
  headingRow.className = "participant-heading";
  const heading = document.createElement("h3");
  heading.textContent = `参与者 ${participantCounter}`;
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "text-button danger remove-participant";
  removeButton.textContent = "移除";
  removeButton.addEventListener("click", () => {
    card.remove();
    updateParticipantRemoveButtons();
    invalidateGroupRanking("参与者已变化，请重新确认并排名。 ");
  });
  headingRow.append(heading, removeButton);

  const nameLabel = document.createElement("label");
  nameLabel.textContent = "称呼";
  nameLabel.htmlFor = `${participantId}-name`;
  const nameInputElement = document.createElement("input");
  nameInputElement.id = `${participantId}-name`;
  nameInputElement.className = "participant-name";
  nameInputElement.value = `参与者 ${participantCounter}`;
  nameInputElement.autocomplete = "off";
  nameInputElement.addEventListener("input", () =>
    invalidateGroupRanking("参与者输入已变化，请重新计算排名。 "),
  );

  const queryLabel = document.createElement("label");
  queryLabel.textContent = "上海出发地";
  queryLabel.htmlFor = `${participantId}-query`;
  const searchRow = document.createElement("div");
  searchRow.className = "inline-field";
  const queryInput = document.createElement("input");
  queryInput.id = `${participantId}-query`;
  queryInput.className = "origin-query";
  queryInput.autocomplete = "off";
  queryInput.placeholder = "例如：人民广场地铁站";
  queryInput.addEventListener("input", () => {
    clearConfirmedOrigin(card, "关键词已改变，请重新选择并确认出发地");
    invalidateGroupRanking("参与者出发地已变化，请重新计算排名。 ");
  });
  const searchButton = document.createElement("button");
  searchButton.type = "button";
  searchButton.className = "button quiet";
  searchButton.textContent = "搜索";
  searchButton.addEventListener("click", () => searchParticipantOrigin(card));
  searchRow.append(queryInput, searchButton);

  const confirmation = document.createElement("p");
  confirmation.className = "origin-confirmation pending";
  confirmation.textContent = "尚未确认出发地";
  const candidates = document.createElement("div");
  candidates.className = "origin-candidates";

  card.append(
    headingRow,
    nameLabel,
    nameInputElement,
    queryLabel,
    searchRow,
    confirmation,
    candidates,
  );
  participantsElement.append(card);
  updateParticipantRemoveButtons();
  invalidateGroupRanking("参与者已变化，请确认所有出发地后排名。 ");
}

function collectParticipants() {
  const cards = [...participantsElement.querySelectorAll(".participant-card")];
  if (cards.length < 2) {
    throw new Error("多人排名至少需要两名参与者。 ");
  }
  return cards.map((card, index) => {
    const name = card.querySelector(".participant-name").value.trim();
    if (!name) {
      throw new Error(`第 ${index + 1} 名参与者缺少称呼。`);
    }
    if (card.dataset.confirmed !== "true") {
      throw new Error(`请先确认 ${name} 的上海出发地。`);
    }
    return {
      participant_id: card.dataset.participantId,
      name,
      address: card.dataset.address,
      longitude: Number(card.dataset.longitude),
      latitude: Number(card.dataset.latitude),
      amap_poi_id: card.dataset.poiId || null,
    };
  });
}

function focusRestaurantOnMap(restaurant) {
  selectRestaurantForLocation(restaurant);
  if (mapInstance && restaurant.longitude !== null && restaurant.latitude !== null) {
    mapInstance.setCenter([restaurant.longitude, restaurant.latitude]);
    mapInstance.setZoom(15);
  }
}

function renderGroupRanking(result) {
  rankingList.replaceChildren();
  excludedList.replaceChildren();
  groupResults.hidden = false;

  const coverage = document.createElement("div");
  coverage.className = result.coverage_complete ? "coverage complete" : "coverage incomplete";
  coverage.textContent = result.coverage_complete
    ? `已检查 ${result.located_count} 家可靠定位门店；${result.ranked.length} 家进入完整排名，实际公交请求 ${result.route_request_count} 次。`
    : `排名未覆盖完整名单：${result.service_error_count} 次路线服务失败；不得把当前结果用于多人随机。`;
  rankingList.append(coverage);

  if (result.ranked.length === 0) {
    appendText(rankingList, "empty-state", "没有餐厅具备所有参与者的有效公共交通方案。 ");
  }
  for (const item of result.ranked) {
    const card = document.createElement("article");
    card.className = "ranking-card";
    const heading = document.createElement("div");
    heading.className = "ranking-heading";
    const title = document.createElement("h3");
    title.textContent = `#${item.rank} ${item.restaurant.name}`;
    const total = document.createElement("strong");
    total.textContent = `总计 ${secondsLabel(item.total_seconds)}`;
    heading.append(title, total);
    card.append(heading);
    appendText(card, "ranking-address", item.restaurant.address);
    appendText(
      card,
      "ranking-location",
      `地图位置：${item.restaurant.longitude.toFixed(5)}, ${item.restaurant.latitude.toFixed(5)} · ${locationLabel(item.restaurant.location_status)}`,
    );

    const routeList = document.createElement("div");
    routeList.className = "person-routes";
    for (const personRoute of item.routes) {
      const routeItem = document.createElement("div");
      routeItem.className = "person-route";
      const routeTitle = document.createElement("strong");
      routeTitle.textContent = `${personRoute.participant_name} · ${secondsLabel(personRoute.duration_seconds)}`;
      const routeSummary = document.createElement("p");
      routeSummary.textContent = personRoute.summary;
      routeItem.append(routeTitle, routeSummary);
      routeList.append(routeItem);
    }
    card.append(routeList);

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const focusButton = document.createElement("button");
    focusButton.type = "button";
    focusButton.className = "text-button";
    focusButton.textContent = "在地图查看 / 更正位置";
    focusButton.addEventListener("click", () => focusRestaurantOnMap(item.restaurant));
    actions.append(focusButton);
    card.append(actions);
    rankingList.append(card);
  }

  const excludedHeading = document.createElement("h3");
  excludedHeading.textContent = `不具备完整比较条件（${result.excluded.length}）`;
  excludedList.append(excludedHeading);
  if (result.excluded.length === 0) {
    appendText(excludedList, "field-help", "没有排除项。 ");
  }
  for (const item of result.excluded) {
    appendText(excludedList, "excluded-item", `${item.restaurant.name}：${item.reason}`);
  }

  latestGroupRankingId = result.ranking_id;
  groupRandomButton.disabled = !result.random_eligible;
  groupStatus.textContent = result.coverage_complete
    ? "排名完成。显示分钟为四舍五入值，排序使用高德返回的原始秒数。"
    : "排名未覆盖完整名单；旧排名已作废，多人随机不可用。";
}

async function runGroupRanking() {
  let participants;
  try {
    participants = collectParticipants();
  } catch (error) {
    invalidateGroupRanking(error.message);
    return;
  }

  invalidateGroupRanking("正在逐家计算公共交通方案，请稍候…", { keepAttempt: true });
  rankButton.disabled = true;
  groupRandomButton.disabled = true;
  try {
    const result = await apiRequest("/api/group/rank", {
      method: "POST",
      body: JSON.stringify({ participants }),
    });
    hasGroupRankingAttempt = true;
    await loadRestaurants();
    renderGroupRanking(result);
  } catch (error) {
    hasGroupRankingAttempt = false;
    invalidateGroupRanking(`排名失败：${error.message}`);
  } finally {
    rankButton.disabled = false;
  }
}

placeSearchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = placeQuery.value.trim();
  if (!activeRestaurant || !query) {
    setFeedback("请先选择餐厅并填写搜索关键词。", "error");
    return;
  }
  placeCandidates.replaceChildren();
  appendText(placeCandidates, "candidate-summary", "正在搜索上海高德 POI…");
  try {
    const result = await apiRequest(`/api/places/search?q=${encodeURIComponent(query)}`);
    renderPlaceCandidates(result);
  } catch (error) {
    placeCandidates.replaceChildren();
    appendText(placeCandidates, "error-text", `地点搜索失败：${error.message}`);
  }
});

manualLocationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!activeRestaurant) {
    setFeedback("请先选择一家餐厅。", "error");
    return;
  }
  const address = locationAddress.value.trim();
  const longitude = Number(locationLongitude.value);
  const latitude = Number(locationLatitude.value);
  if (!address || !Number.isFinite(longitude) || !Number.isFinite(latitude)) {
    setFeedback("保存人工位置需要可核对的地址和有效经纬度。", "error");
    return;
  }
  try {
    const shouldRerank = hasGroupRankingAttempt;
    const saved = await apiRequest(`/api/restaurants/${activeRestaurant.id}/location`, {
      method: "PATCH",
      body: JSON.stringify({
        address,
        longitude,
        latitude,
        amap_poi_id: locationPoiId.value || null,
      }),
    });
    invalidateGroupRanking("门店位置已更正，旧路线和排名已失效。 ", {
      keepAttempt: shouldRerank,
    });
    await loadRestaurants();
    activeRestaurant = saved;
    if (shouldRerank) {
      setFeedback(`已人工确认“${saved.name}”的位置，正在使用原参与者重新排名。`);
      await runGroupRanking();
    } else {
      setFeedback(`已人工确认“${saved.name}”的位置。`);
    }
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

resolveAllButton.addEventListener("click", async () => {
  clearFeedback();
  batchResults.hidden = false;
  batchResults.replaceChildren();
  appendText(batchResults, "candidate-summary", "正在逐家尝试自动定位…");
  try {
    const payload = await apiRequest("/api/restaurants/resolve-locations", { method: "POST" });
    batchResults.replaceChildren();
    const labels = {
      auto_resolved: "已自动定位",
      needs_confirmation: "需要人工选择",
      no_candidates: "无候选",
      protected_manual: "已人工确认，跳过",
      already_resolved: "已有自动位置，跳过",
      conflict: "文件已变化，未保存",
      skipped_service_failures: "连续服务失败，停止后续请求",
      error: "请求失败",
    };
    for (const result of payload.results) {
      const suffix = result.error ? `：${result.error}` : "";
      appendText(
        batchResults,
        `batch-item ${result.status}`,
        `${result.name} — ${labels[result.status] || result.status}${suffix}`,
      );
    }
    invalidateGroupRanking("门店定位状态已变化，请重新计算多人排名。 ");
    await loadRestaurants();
    setFeedback("批量定位已完成；模糊或多候选记录仍需人工确认。 ");
  } catch (error) {
    batchResults.replaceChildren();
    appendText(batchResults, "error-text", `批量定位失败：${error.message}`);
  }
});

formElement.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFeedback();

  const name = nameInput.value.trim();
  const restaurantType = typeInput.value.trim();
  const detail = detailInput.value.trim();
  const dianpingUrl = dianpingUrlInput.value.trim();
  if (dianpingShareInput.value.trim() && !dianpingShareAccepted) {
    setFeedback("请先解析并采用点评分享预览，再保存餐厅。", "error");
    return;
  }
  if (tagInput.value.trim()) {
    addPendingTag({ showEmptyError: false });
  }
  if (!name) {
    const message = dianpingUrl
      ? "大众点评链接不会自动识别门店，请补填餐厅名称。"
      : "请填写餐厅名称。";
    setFeedback(message, "error");
    nameInput.focus();
    return;
  }
  if (!restaurantType || !detail) {
    setFeedback("请完整填写类型和菜系。", "error");
    return;
  }

  const payload = {
    name,
    type: restaurantType,
    detail,
    dianping_url: dianpingUrl || null,
    tags: [...editingTags],
  };
  const editingId = idInput.value;
  try {
    if (editingId) {
      await apiRequest(`/api/restaurants/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setFeedback(`已保存“${name}”的修改。`);
    } else {
      await apiRequest("/api/restaurants", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setFeedback(`已添加“${name}”。`);
    }
    resetEditor();
    randomResult.hidden = true;
    invalidateGroupRanking("餐厅名单已变化，旧多人排名已失效。 ");
    await loadRestaurants();
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

cancelButton.addEventListener("click", resetEditor);
addTagButton.addEventListener("click", () => addPendingTag());
tagInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addPendingTag();
  }
});

dianpingShareInput.addEventListener("input", () => {
  clearDianpingPreview();
});

parseDianpingButton.addEventListener("click", async () => {
  clearFeedback();
  clearDianpingPreview();
  const text = dianpingShareInput.value.trim();
  if (!text) {
    setFeedback("请粘贴大众点评商户链接或完整分享文字。", "error");
    return;
  }
  try {
    const result = await apiRequest("/api/dianping/parse", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    renderDianpingPreview(result);
    setFeedback(
      result.requires_name
        ? "链接有效，但无法从链接可信取得店名；采用链接后请补填名称。"
        : "已在本地解析分享内容；请核对预览并采用后再保存。",
    );
  } catch (error) {
    setFeedback(`点评分享解析失败：${error.message}`, "error");
  }
});

useDianpingButton.addEventListener("click", () => {
  if (!parsedDianpingResult) {
    setFeedback("请先解析点评分享。", "error");
    return;
  }
  if (parsedDianpingResult.name_suggestion) {
    nameInput.value = parsedDianpingResult.name_suggestion;
  }
  dianpingUrlInput.value = parsedDianpingResult.url;
  dianpingShareAccepted = true;
  if (parsedDianpingResult.requires_name && !nameInput.value.trim()) {
    setFeedback("已采用商户链接；链接不能提供可信店名，请补填餐厅名称。", "error");
    nameInput.focus();
    return;
  }
  setFeedback("已采用解析结果；名称和链接仍可编辑，保存即表示确认。 ");
});

openDataDirectoryButton.addEventListener("click", async () => {
  try {
    await apiRequest("/api/runtime/open-data-directory", { method: "POST" });
    setFeedback("已请求 Windows 打开当前名单所在目录。 ");
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

importRestaurantsButton.addEventListener("click", async () => {
  const file = restaurantImportFile.files[0];
  if (!file) {
    importStatus.textContent = "请先选择一个 JSON 文件。";
    return;
  }
  if (!window.confirm("导入会替换当前名单；程序将先自动备份。确定继续吗？")) {
    return;
  }
  importRestaurantsButton.disabled = true;
  try {
    const result = await apiRequest("/api/data/import", {
      method: "POST",
      body: JSON.stringify({ json_text: await file.text() }),
    });
    importStatus.textContent = `已导入 ${result.count} 家；原名单备份在 ${result.backup_path}`;
    restaurantImportFile.value = "";
    invalidateGroupRanking("餐厅名单已导入，旧多人排名已失效。 ");
    await loadRestaurants();
  } catch (error) {
    importStatus.textContent = `导入失败：${error.message}`;
  } finally {
    importRestaurantsButton.disabled = false;
  }
});

amapSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    web_service_key: amapWebKey.value,
    js_api_key: amapJsKey.value,
    js_security_key: amapSecurityKey.value,
  };
  try {
    await apiRequest("/api/settings/amap", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    amapSettingsForm.reset();
    await loadAmapSettingsStatus();
    setFeedback("高德配置已保存到当前 Windows 用户保护存储；刷新页面后加载地图。 ");
  } catch (error) {
    amapSettingsStatus.textContent = `保存失败：${error.message}`;
  }
});

randomButton.addEventListener("click", async () => {
  clearFeedback();
  try {
    const result = await apiRequest("/api/random", { method: "POST" });
    randomNumber.textContent = String(result.number);
    randomTotal.textContent = String(result.total);
    randomName.textContent = result.restaurant.name;
    randomType.textContent = result.restaurant.type;
    randomResult.hidden = false;
  } catch (error) {
    randomResult.hidden = true;
    setFeedback(error.message, "error");
  }
});

addParticipantButton.addEventListener("click", addParticipant);
rankButton.addEventListener("click", runGroupRanking);
groupRandomButton.addEventListener("click", async () => {
  groupRandomResult.hidden = true;
  if (!latestGroupRankingId) {
    groupStatus.textContent = "当前没有成功且未失效的完整排名，无法多人随机。";
    return;
  }
  try {
    const result = await apiRequest("/api/group/random", {
      method: "POST",
      body: JSON.stringify({ ranking_id: latestGroupRankingId }),
    });
    groupRandomResult.replaceChildren();
    appendText(
      groupRandomResult,
      "group-random-number",
      `${result.number} / ${result.total}`,
    );
    appendText(
      groupRandomResult,
      "group-random-name",
      `${result.restaurant.name} · ${result.restaurant.type}`,
    );
    groupRandomResult.hidden = false;
  } catch (error) {
    invalidateGroupRanking(`多人随机不可用：${error.message}`);
  }
});

addParticipant();
addParticipant();

loadRestaurants();
loadMapConfiguration();
loadRuntimeInfo();
loadAmapSettingsStatus();
window.addEventListener("focus", loadRestaurants);
