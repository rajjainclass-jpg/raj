(() => {
  'use strict';
  const status = document.getElementById('status');
  const reference = document.getElementById('reference');
  const pay = document.getElementById('pay');
  const back = document.getElementById('return');
  const params = new URLSearchParams(window.location.hash.slice(1));
  const session = params.get('session');
  const order = params.get('order');
  const mode = params.get('mode');
  const returnedOrder = new URLSearchParams(window.location.search).get('return_order');
  // The session arrives in a fragment, never in the HTTP request or Referer.
  // Remove it from the visible URL and history immediately. No local storage or analytics.
  if (window.location.hash) window.history.replaceState(null, '', window.location.pathname);
  const catalog = document.getElementById('products');
  fetch('https://rpdfdvvmvlstbqxtdwip.supabase.co/rest/v1/rpc/raj_api', {
    method:'POST',headers:{'Content-Type':'application/json',apikey:'sb_publishable_W0cih8e_Lu9EyxwE6GmWLg_AJTkP4LH'},
    body:JSON.stringify({p_method:'GET',p_route:'products',p_body:{},p_query:{limit:'12'}})
  }).then(r => {if(!r.ok)throw Error('unavailable');return r.json();}).then(data => {
    catalog.replaceChildren();
    for (const product of data.products || []) {
      const row = document.createElement('p');
      row.textContent = product.name + ' · ' + new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(product.sellingPaise/100) + (product.available ? '' : ' · Sold out');
      catalog.append(row);
    }
    if(!catalog.children.length)catalog.textContent='Contact the shop for current products and prices.';
  }).catch(() => {catalog.textContent='Open the Customer app or call the shop for current products and prices.';});
  if (!session || !order) {
    if(returnedOrder && /^rkp_[a-f0-9]{32}$/.test(returnedOrder)) {
      status.textContent='Return to the RAJ Kirana app to verify your payment status.';
      back.href='rajkirana-online://payment-return?orderId='+encodeURIComponent(returnedOrder);
      back.hidden=false;
    }
    return;
  }
  if (!/^rkp_[a-f0-9]{32}$/.test(order) || session.length < 8 || session.length > 16000 || !['production','sandbox'].includes(mode)) {
    status.textContent = 'This checkout link is incomplete. Open the same order from the Customer app again.';
    return;
  }
  const returnUri = 'rajkirana-online://payment-return?orderId=' + encodeURIComponent(order);
  back.href = returnUri;
  back.hidden = false;
  reference.textContent = 'Order ' + order.slice(4,12) + (mode === 'sandbox' ? ' · Sandbox test' : '');
  status.textContent = 'Continue to Cashfree to choose your payment method. Return to the app afterward to confirm the order status.';
  pay.hidden = false;
  let running = false;
  pay.addEventListener('click', async () => {
    if (running) return;
    if (typeof window.Cashfree !== 'function') {
      status.textContent = 'Cashfree could not load. Check your connection and retry this same order from the app.';
      return;
    }
    running = true; pay.disabled = true;
    status.textContent = 'Opening Cashfree secure checkout…';
    try {
      const cashfree = window.Cashfree({mode});
      const result = await cashfree.checkout({paymentSessionId:session,redirectTarget:'_modal'});
      if (result && result.error) {
        const message = String(result.error.message || 'Checkout was closed or could not complete.');
        status.textContent = message.replaceAll(session,'[hidden]').slice(0,280) + ' Return to the app and check payment status before retrying.';
      } else {
        status.textContent = 'Return to the RAJ Kirana app to verify your payment status. This page does not confirm payment.';
      }
    } catch (_) {
      status.textContent = 'Cashfree checkout could not complete. Return to the app and check this order before retrying.';
    } finally {running = false;pay.disabled = false;}
  });
})();
