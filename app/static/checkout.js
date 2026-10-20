(() => {
  const fulfillment = document.querySelector("#fulfillment");
  const deliveryFields = ["#delivery-field", "#order-notes-field"].map((selector) => document.querySelector(selector));
  const pickupField = document.querySelector("#pickup-field");
  const deliveryTotal = document.querySelector("#delivery-total");
  const checkoutTotal = document.querySelector("#checkout-total");
  if (!fulfillment) return;
  const update = () => {
    const isDelivery = fulfillment.value === "delivery";
    deliveryFields.forEach((field) => {
      if (field) {
        field.hidden = !isDelivery;
        field.querySelectorAll("input, textarea, select").forEach((control) => {
          control.required = isDelivery && (control.name === "delivery_address" || control.name === "delivery_zone");
        });
      }
    });
    if (pickupField) {
      pickupField.hidden = isDelivery;
      pickupField.querySelectorAll("input").forEach((control) => {
        control.required = !isDelivery;
      });
    }
    if (deliveryTotal && checkoutTotal) {
      const fee = Number(deliveryTotal.dataset[isDelivery ? "delivery" : "pickup"] || 0);
      const subtotal = Number(checkoutTotal.dataset.subtotal || 0);
      const tax = Number(checkoutTotal.dataset.tax || 0);
      deliveryTotal.textContent = `R ${(fee / 100).toFixed(2)}`;
      checkoutTotal.textContent = `R ${((subtotal + fee + tax) / 100).toFixed(2)}`;
    }
  };
  fulfillment.addEventListener("change", update);
  update();
})();