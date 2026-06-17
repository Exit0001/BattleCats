/* Battle Cats Shop — Thai/English switcher
   Safe by design: default language is Thai (zero change from original page).
   Only swaps textContent/innerHTML of elements marked [data-i18n]; never
   touches onclick handlers, ids, classes, or app logic. */
(function () {
  'use strict';

  var STORAGE_KEY = 'bc_lang';

  /* ── Dictionary: English text only — Thai is whatever is already in the HTML ── */
  var EN = {
    // Nav (shared across all pages)
    nav_home:         'Home',
    nav_shop:         'Item Shop',
    nav_shop_codes:   'Ready Codes',
    nav_unlock_cat:   'Unlock Cats',
    nav_unlock_stage: 'Unlock Stages',
    nav_orders:       'Orders',
    nav_loyalty:      'Loyalty Points',

    // index.html
    idx_badge:          'Battle Cats — Trending Worldwide',
    idx_hero_sub:       'Items • Cats • Cat Food • Stages at the best price!',
    idx_view_shop:      'View Item Shop',
    idx_stat_customers: 'Customers',
    idx_stat_delivery:  'Delivery',
    idx_stat_secure:    'Secure',
    idx_hot_products:   'Best Sellers',
    idx_catfood_desc:    'The biggest cat food bundle — spin Gacha all day',
    idx_rareticket_desc: 'Max Rare Tickets — redeem instantly, no ban risk',
    idx_catfruit_desc:   'True Form Catfruit — the essential material',
    idx_cateye_desc:     'Level up past the limit, boost every cat',
    buy_now:            'Buy Now',
    idx_services_title:     'Our Services',
    idx_service_shop_desc:  'Buy items and Cat Food',
    go_to_shop:             'Go to Shop',
    idx_service_cat_desc:   'Unlock rare cats',
    view_cats:              'View Cats',
    idx_service_stage_desc: "Clear the stages you're stuck on",
    view_stages:            'View Stages',
    idx_why_us:        'Why Choose Us',
    trust_fast_title:  'Instant Delivery',
    trust_fast_sub:    'Receive items in 5 minutes',
    trust_safe_title:  '100% Safe',
    trust_safe_sub:    'Ban-free, guaranteed',
    trust_support_sub: 'Available 24/7',
    trust_pay_title:   'Easy Payment',
    footer_brand_desc: 'Professional Battle Cats item service. Safe, fast, and ban-free.',
    footer_services:   'Services',
    nav_orders_mine:   'My Orders',
    footer_contact:    'Contact Us',
    fb_user:           'Facebook (Personal)',
    fb_page:           'Facebook (Shop Page)',
    lang_pill:         'Thai / English',
    verified_pill:     'Verified',
    users_pill:        'Users',
    footer_bottom:     'This service is not an official PONOS product',

    // shop.html
    shop_title:        '🛍️ Item Shop',
    shop_banner_title: '💡 Tips before you order, for the best value',
    shop_banner_l1:    '• Items have a <strong style="color:#FDE047;">Max</strong> cap in-game — for your account\'s safety, please check your current amount before ordering, because anything over the cap gets cut automatically by the game.',
    shop_banner_l2:    '• We recommend buying just enough to reach <span style="color:#FDE047;font-weight:700;">Max</span> — so you don\'t waste the extra for nothing!',
    add_to_cart:       'Add to Cart',
    shop_section_catfruit: '🍎 Catfruit',
    shop_tag_mega_best: 'MEGA BEST VALUE',
    shop_catfood_10k:  'Add 10,000 Cat Food',
    shop_catfood_20k:  'Add 20,000 Cat Food',
    shop_catfood_30k:  'Add 30,000 Cat Food',
    shop_catfood_45k:  'Add 45,000 Cat Food',
    shop_xp_max:       'Add max XP in one go',
    shop_nt_good:      'Chance for good cats',
    shop_nt_rare:      'Try your luck for rare cats',
    shop_nt_safe:      'Safe, no ban risk',
    shop_nt_sr:        'Chance for 1 Super Rare!',
    shop_rt_howto_title: '⚠️ How to use Rare Tickets (read this first!)',
    shop_rt_step1:     '① Receive Item',
    shop_rt_step2:     '② Go to Storage',
    shop_rt_step3:     '③ Use All',
    shop_rt_step4:     '④ Trade for Gold Ticket',
    shop_rt_trade:     'Uses Trade Route for safety',
    shop_rt_rare:      'Try for rare cats with Rare Tickets',
    shop_rt_big:       'Big bundle of Rare Tickets',
    shop_rt_max:       'Max Rare Ticket bundle',
    shop_battleitem_choose: 'Choose Battle Item type (1-6)',
    shop_np_instant:   'Add in-game money instantly',
    shop_np_accum:     'Add to NP balance',
    shop_np_big:       'Great for big purchases',
    shop_np_max:       'Max NP — best value per unit',
    shop_ps_collect:   'Collect for a Platinum Ticket',
    shop_ps_mid:       'Mid bundle for the leaderboard',
    shop_ps_big:       "Big bundle, close to a Gold Ticket",
    shop_ps_best:      'Best value for a Platinum Ticket',
    shop_ld_team:      'Add Leadership for a stronger team',
    shop_ld_battle:    'Add Leadership for battle',
    shop_ld_big:       'Big bundle for your team',
    shop_ld_max:       'Max Leadership',
    shop_ce_choose:    'Choose Catseye type (1-6)',
    shop_cfr_choose:   'Choose Catfruit type (1-29)',
    shop_cam_choose:   'Choose Catamins type (1-3)',
    shop_lt_add:       'Add Legend Tickets',
    shop_luck_press:   'Adds Lucky Tickets — use them for a shot at special in-game rewards',
    shop_rare_ticket_limit: '⚠️ You can only add 1 Rare Ticket item per order\nBecause you must claim it from Storage before doing it again',
    shop_max_reached: '⚠️ {item} in your cart has reached the max ({max}) — you can\'t add more',
    shop_max_exceed: '⚠️ Can\'t add — it would exceed the max ({max})\nYou can still add {left} more',
    shop_added_to_cart: '✅ Added {item} to cart!',

    // shop-codes.html
    sc_title:  '🎮 Ready-Made Codes',
    sc_banner: '💡 Buy a ready-made code — get your Transfer Code + Confirmation Code instantly after payment, no need to wait for an admin<br>' +
               '<span style="color:rgba(253,224,71,0.5)">• You must be logged in to buy &nbsp;•&nbsp; Pay via PromptPay or TrueWallet</span>',
    sc_empty_products: 'No products available right now',
    sc_no_image: 'No image',
    sc_stock_out: 'Out of stock',
    sc_stock_low: '{n} left',
    sc_stock_ok:  '{n} in stock',
    sc_pay_title: '💳 Payment',
    sc_qr_loading: 'Generating QR...',
    sc_qr_scan_hint: 'Scan with your banking app or Pao Tang',
    sc_amount_label: 'Amount:',
    sc_dont_close: '⚠ Do not close this page until the slip is uploaded',
    sc_upload_slip_label: 'Upload transfer slip',
    sc_submit_slip_btn: '📤 Submit slip for verification',
    sc_tw_loading: 'Creating order...',
    sc_tw_info: 'Send an Angpao gift voucher matching the amount below, then paste the code/link in the box below',
    sc_tw_base_label: 'Item price:',
    sc_tw_fee_label: 'TrueWallet fee 2.9% (max 20 baht):',
    sc_tw_total_label: 'Amount to pay:',
    sc_tw_warn: '⚠️ Do not close this page until the Angpao code is sent',
    sc_tw_transfer_label: 'Transfer to TrueWallet number:',
    sc_tw_paste_label: 'Paste TrueWallet Angpao link',
    sc_tw_submit_btn: '💚 Confirm payment with TrueWallet',
    sc_paid_success: '✅ Payment complete! Here is your code',
    sc_save_code_warn: '⚠ Save this code before closing',
    close_btn: 'Close',
    sc_pd_feature1: '✅ Get the code instantly after payment',
    sc_pd_payment_method: 'Payment Method',
    sc_pd_pay_warn: '⚠ Please choose a payment method before buying',
    sc_pd_buy_btn: '🛒 Buy Now',
    sc_pd_out_of_stock: 'Out of stock',
    sc_login_before_buy: 'Please log in before purchasing',
    sc_loading_products: 'Loading products...',

    // stages.html
    stg_title: '📍 Unlock Stages',
    stg_subtitle: 'Tap a card to choose a service',
    stg_choose_service: 'Choose Service',
    stg_aku_desc: 'Unlock the Dark World and/or clear Aku Chapters',
    stg_aku_land: 'Land of Aku',
    stg_trust_safe_sub: 'No ban risk',
    stg_trust_fast: 'Fast',
    stg_trust_fast_sub: 'Within 5 minutes',
    stg_trust_perm: 'Permanent',
    stg_trust_perm_sub: 'Stages cleared permanently',
    stg_total_label: 'Total',
    stg_add_cart: 'Add to Cart',
    stg_modal_total: 'Total for this card',
    stg_save_cart: 'Save to Cart',
    stg_pay_for: 'Payment for',
    stg_server_jp: 'JP (Japan)',
    stg_server_kr: 'KR (Korea)',
    stg_server_tw: 'TW (Taiwan)',
    stg_pay_now: 'Pay Now',
    stg_scan_qr: 'Scan the PromptPay QR to pay',
    sc_tw_info_short: 'Send an Angpao gift voucher matching the amount below',
    stg_upload_slip_after: 'After transferring, upload your slip below',
    stg_choose_slip_file: 'Choose slip file',
    stg_verify_payment: 'Verify Payment',
    stg_success: 'Success!',
    stg_new_tc: 'New Transfer Code (tap to copy)',
    stg_new_cc: 'New Confirmation Code',
    stg_processing: 'Processing...',
    stg_choose_chapter: 'Choose Chapter',
    stg_clear_label: '📖 Clear Story',
    stg_clear_desc: 'Clear all main stages in {title}',
    stg_treasure_label: '🏆 Gold Treasure',
    stg_treasure_desc: 'Fill Gold Treasure in every stage of the chapter',
    stg_zombie_label: '🧟 Zombie Clear',
    stg_zombie_desc: 'Clear Outbreak (Zombie) chapters',
    stg_legend_clear_desc: 'Clear all stages with the selected crown count',
    stg_crown_count: 'Crown Count',
    stg_aku_unlock_label: '🔓 Unlock Aku Realm',
    stg_aku_unlock_desc: 'Unlock the Aku Dark World',
    stg_aku_chapters_label: '⚔️ Clear Aku Chapters',
    stg_aku_chapters_desc: 'Clear Aku Chapters',
    stg_edit_service: 'Edit Service',
    stg_toast_updated: 'Cart updated ✅ ({n} services)',
    stg_toast_removed: 'Removed this card\'s services from the cart',
    stg_choose_service_first: 'Please choose a service first',
    stg_cart_empty: 'Your cart is empty — choose a service first',
    stg_toast_added: 'Added {n} services to cart ✅',
    stg_enter_codes: 'Please enter the Transfer Code and Confirmation Code',
    stg_error_generic: 'Something went wrong',
    stg_api_error: 'Could not connect to API: ',
    stg_verify_failed: 'Payment verification failed',
    stg_copied: '✅ Copied!',

    // orders.html
    ord_title: '🛒 Order System',
    ord_tab_order: '🛒 Order',
    ord_tab_history: '📋 History',
    ord_summary_title: '💳 Order Summary',
    ord_items_label: 'Items:',
    ord_items_unit: '{n} item(s)',
    ord_total_label: 'Total:',
    ord_hint: '📌 Fill in your Transfer Code, Confirmation Code, and server completely so BCSFE can process your order',
    ord_video_howto_tc: '🎬 How to find your Transfer Code in-game',
    ord_tc_hint: 'From: Settings → Change Device → Save Data to Server',
    ord_select_placeholder: '-- Select --',
    ord_server_tip: '💡 If you play on a normal Thai server, choose <strong style="color:#FCD34D;">EN</strong>',
    ord_important_warn: '<strong style="color: #ffb347;">⚠️ Important:</strong> Do not log into the game while waiting for the edit — it will expire your Transfer Code!',
    ord_pay_method_lock: '⚠️ Payment pending — please cancel the order before changing payment method',
    ord_proceed_pay: '💳 Proceed to Payment',
    ord_continue_shopping: 'Continue Shopping',
    ord_amount_due: 'Amount due',
    ord_tm_video_title: '🎬 How to send a TrueWallet Angpao',
    ord_tm_exact_amount: '⚠️ The amount must match exactly — no more, no less',
    ord_paste_voucher: 'Paste Angpao code/link',
    ord_submit_voucher_btn: '📤 Submit code for verification',
    ord_cancel_order_btn: 'Cancel this order (not paid yet)',
    ord_cancel_confirm_title: 'Confirm cancel order?',
    ord_cancel_confirm_sub: 'If you already paid, please contact an admin before confirming',
    ord_cancel_confirm_btn: 'Confirm Cancel',
    ord_cancel_no_btn: 'No',
    ord_cart_title: '🛍️ Shopping Cart',
    ord_cart_empty: 'Your cart is empty',
    ord_login_first: 'Please log in first',
    ord_login_to_view_history: 'to view your order history',
    ord_login_btn: 'Log In',
    ord_retry_btn: '🔄 Try Again',
    ord_summary_recap: 'Order Summary:',
    ord_back_to_shop: 'Back to add more items',
    ord_qty_label: ' • Qty ',
    ord_remove_btn: 'Remove',
    ord_stage_mix_warn: '⚠️ Your cart has <strong>Unlock Stages</strong> mixed with other items — please remove the stage items first and pay separately',
    ord_stage_only_hint: '📍 This is an <strong>Unlock Stages</strong> order — once paid, it will be processed automatically',
    ord_cat_only_hint: '🐱 This is an <strong>Unlock Cats</strong> order — once paid, it will be unlocked automatically',
    ord_stage_separate_alert: '⚠️ Please pay for stages separately from other items\nRemove the stage items first, then pay for this order',
    ord_hint_label_unlock: '<strong>Unlock Cats</strong>',
    ord_hint_label_percat: '<strong>Per-Cat Services</strong> (Upgrade/TrueForm/UltraForm/Talents)',
    ord_hint_label_stage: '<strong>Unlock Stages</strong>',
    ord_hint_label_item: '<strong>Items</strong>',
    ord_hint_multi: '🛍️ Your cart has {parts} — the system will process them in order automatically',
    ord_hint_percat_only: '✨ This cart has <strong>Per-Cat Services</strong> — the system will process it automatically after payment',
    copy_done: '✓ Copied!',
    copy_label: 'Copy',
    ord_cart_locked_alert: '⚠️ Cannot edit cart because the payment QR has already been generated\nIf you need to change it, please refresh the page to start over',
    ord_fill_required_alert: '❌ Please fill in Transfer Code, Confirmation Code, and select a Server!',
    ord_empty_cart_alert: '❌ Your cart is empty!',
    ord_submitting: 'Submitting...',
    ord_pay_now_btn: '🚀 Pay Now',
    ord_create_order_failed: 'Could not create the order',
    ord_create_order_failed_alert: '❌ Could not create the order: ',
    ord_pay_via_truewallet: '💳 Pay via TrueWallet',
    ord_pay_via_promptpay: '💳 Pay via PromptPay',
    ord_choose_slip_alert: '❌ Please choose a slip file first',
    ord_checking_slip_btn: '⏳ Checking slip...',
    ord_checking_slip_msg: '🔍 Verifying slip with SlipOK...',
    ord_slip_verify_failed: 'Slip verification failed',
    ord_slip_passed_redo_codes: '⚠️ Slip verified — please enter a new Transfer/Confirmation Code in the popup',
    ord_paid_success_msg: '✅ Payment successful! The system has processed it automatically',
    ord_paste_voucher_warn: '⚠️ Please paste the Angpao code/link',
    ord_no_orderid_alert: '❌ Order ID not found',
    ord_checking_voucher_btn: '⏳ Checking Angpao...',
    ord_checking_voucher_msg: '🔍 Redeeming Angpao with TrueWallet...',
    ord_voucher_verify_failed: 'Angpao verification failed',
    ord_voucher_passed_redo_codes: '⚠️ Angpao verified — please enter a new Transfer/Confirmation Code in the popup',
    ord_loading: '⏳ Loading...',
    ord_no_history_title: 'No order history yet',
    ord_no_history_sub: 'Place an order to see your history here',
    ord_load_history_failed: '❌ Could not load history: ',
    ord_retry_short: '🔄 Try Again',
    ord_admin_contact_label: '⚠️ Latest code — please contact an admin',
    ord_new_label: ' (new)',
    ord_codeshop_label: '🎮 Your ready-made code',
    ord_rare_ticket_howto_hint: '📌 How to use your Rare Ticket: Receive item → Storage (fridge) → Use All → Trade for Gold Ticket',
    ord_success_title: 'Order Successful!',
    ord_partial_success_title: 'Payment received — please fix your Code',
    ord_success_summary: 'BCSFE processed successfully! Use the new Transfer Code to load the save in-game',
    ord_partial_success_summary: 'Your payment was received, but the Transfer/Confirmation Code was invalid. Please re-enter it',
    ord_order_hash: 'Order #',
    ord_new_tc_label: 'NEW TRANSFER CODE',
    ord_new_cc_label: 'NEW CONFIRMATION CODE',
    ord_video_howto_newcode: '🎬 How to enter the new code in-game',
    ord_money_safe_msg: '💡 Your money is safe — enter a new Transfer Code and Confirmation Code, then try again',
    ord_new_tc_field_label: 'New Transfer Code',
    ord_enter_both_codes_alert: '❌ Please enter both Transfer Code and Confirmation Code',
    ord_processing_btn: '⏳ Processing...',
    ord_processing_msg: '🔄 Processing — this takes 1-3 minutes',
    ord_retry_failed: 'Retry failed',
    ord_retry_failed_suffix: ' — check the code and try again',

    // loyalty.html
    loy_hero_title: 'Loyalty Rewards Program',
    loy_hero_sub: 'Shop with us and get free rewards!<br><strong style="color:#fbbf24;">Every ฿200</strong> spent earns 1 redemption — repeat as many times as you like',
    loy_how1_title: 'Place an Order',
    loy_how1_desc: 'Shop normally — your spend accumulates automatically after payment',
    loy_how2_title: 'Reach ฿200',
    loy_how2_desc: 'Track your progress on this page — once you hit ฿200 you get a redemption instantly',
    loy_how3_title: 'Redeem for Free',
    loy_how3_desc: 'Enter your Transfer Code and get items sent straight into your game — never expires',
    loy_member_label: 'Member',
    loy_ready_to_redeem: 'Ready to Redeem',
    loy_loading: 'Loading...',
    loy_stat_total: 'Total Spent',
    loy_stat_redeemed: 'Redeemed',
    loy_stat_next: 'Next Reward At',
    loy_progress_label: 'Progress',
    loy_reward_section_title: 'Rewards (per redemption)',
    loy_reward_normal_ticket: 'Normal Ticket (Silver Ticket)',
    loy_reward_rare_ticket: 'Rare Ticket (Gold Ticket)',
    loy_ready_badge: 'Ready!',
    loy_redeem_title: '✨ Redeem Reward',
    loy_redeem_sub: 'Enter your current in-game Transfer Code, then redeem — items go straight into your game',
    loy_country_label: 'Country',
    loy_redeem_one_btn: '🎁 Redeem 1',
    loy_redeem_all_btn: '⚡ Redeem All',
    loy_history_title: '📜 Redemption History',
    loy_hide_btn: 'Hide ▲',
    loy_view_history_btn: '📜 View Redemption History',
    loy_login_wall_title: 'Log in to see your points',
    loy_login_wall_sub: 'Free to join · Your spend accumulates automatically on every order',
    loy_login_signup_btn: '🔑 Log In / Sign Up',
    loy_ready_redeem_now: 'Tap to redeem!',
    loy_wait_more: 'Keep collecting',
    loy_tc_placeholder: 'e.g. a1b2c3d4e',
    loy_cc_placeholder: 'e.g. 1234',
    loy_times_unit: ' times',
    loy_progress_done: '✅ Complete!',
    loy_progress_msg_ready: '🎉 You have {n} redemption(s) ready — claim it below',
    loy_progress_msg_wait: 'Just ฿{n} more to earn a reward',
    loy_load_failed: 'Could not load data — try refreshing',
    loy_show_btn: 'Show ▼',
    loy_hide_btn2: 'Hide ▲',
    loy_no_history: 'No redemption history yet',
    loy_redeemed_n: '🎁 Redeemed {n} time(s)',
    loy_new_tc_label: 'New Transfer Code',
    loy_tap_to_copy: 'Tap to copy 📋',
    loy_copied: '✅ Copied!',
    loy_rt_howto_title: '⚠️ How to use Rare Tickets (read this first!)',
    loy_rt_step1: 'Receive item',
    loy_rt_step2: 'Storage<br>(fridge)',
    loy_rt_step3: 'Use<br>All',
    loy_rt_step4: 'Trade for Gold',
    loy_enter_codes_alert: 'Please enter the Transfer Code and Confirmation Code',
    loy_no_cycles_alert: 'No redemptions available',
    loy_redeeming_btn: '⏳ Processing...',
    loy_redeem_now_btn: '🎁 Redeem Now',
    loy_redeem_success: '🎉 Reward claimed!',
    loy_remaining_cycles: '🎁 You still have {n} redemption(s) left — claim more anytime',
    loy_generic_error: 'Something went wrong',
    loy_connect_failed: '❌ Could not connect to the server',
    loy_redeeming_n_btn: '⏳ Processing {n} redemption(s)...',
    loy_redeem_all_done: '🎉 Claimed {n} redemption(s) at once!',

    // characters.html
    char_title: '🐱 Unlock Cats',
    char_subtitle: 'Search for the cat you need — images pulled directly from the Battle Cats Wiki',
    char_pkg_title: '🌟 Special Packages — Whole Save Account',
    char_pkg_sub: 'Process every character at once — better value than ordering one by one',
    char_upgrade_all_name: 'Max Upgrade<br>Every cat in your save',
    char_upgrade_all_desc: 'Uber Lv60 · SR/R Lv50 · Normal Lv30<br>Your existing Plus levels stay the same',
    add_to_cart_plus: '+ Add to Cart',
    char_unlock_all_name: 'Unlock Every<br>Character in the Game',
    char_unlock_all_desc: 'Unlocks <strong style="color:#EDE6FF;">every cat in the game</strong><br>Including Uber · Special, no exceptions',
    char_trueform_all_name: 'True Form<br>Every cat in your save',
    char_trueform_all_desc: 'Turns every cat you own<br>into True Form (3rd form)',
    char_ultraform_all_name: 'Ultra Form<br>Every cat in your save',
    char_ultraform_all_desc: 'Turns every cat with a 4th form<br>into Ultra Form (4th form)',
    char_talents_all_name: 'Max Talents<br>Every cat in your save',
    char_talents_all_desc: 'Maxes every Talent skill<br>for every cat with Talents in your save',
    char_cat_count_9: 'Cat #91–99 (9 cats)',
    char_crazed_desc: 'Unlocks <strong style="color:#EDE6FF;">9 Crazed Cats</strong><br>Cat ID #91–99, all of them',
    char_manic_desc: 'True Form for <strong style="color:#EDE6FF;">9 Manic Cats</strong><br>Cat ID #91–99 (requires Crazed first)',
    char_manic_warn: '⚠️ Requires Cat #91–99 already at Lv.30',
    char_search_title: '🔎 Search Characters',
    char_search_desc: 'Services: <strong style="color:#c4b5fd;">Unlock · Upgrade · True Form · Ultra Form · Talents</strong> — just pick the character, no need to enter the ID yourself',
    filter_all: 'All',
    filter_search_btn: 'Search',
    filter_reset_btn: 'Reset',
    char_search_placeholder: 'Search by name or ID, e.g. 86, Valkyrie, Kamukura…',
    char_trust_permanent: 'Permanently Unlocked',
    char_trust_permanent_sub: 'Cats you get stay forever',
    char_trust_safe_sub: 'No risk of getting banned',
    char_trust_fast: 'Fast Delivery',
    char_trust_fast_sub: 'Get your cats within 5 minutes',
    char_trust_count: '860+ Characters',
    char_trust_count_sub: 'Covers every tier',
    char_choose_btn: 'Choose',
    char_no_results: 'No matching characters found',
    char_svc_unlock: 'Unlock',
    char_svc_upgrade: 'Max Upgrade',
    char_svc_trueform_note: 'Only for characters with a True Form, at Lv.30 or higher',
    char_svc_ultraform_note: 'Only for characters with an Ultra Form, and must already have True Form',
    char_svc_talents_note: 'Only for characters with Talents',
    char_in_cart: '✓ In Cart',
    char_choose_service_for: 'Choose a service for',
    char_already_in_cart: '⚠ {name} is already in your cart!',
    char_added_to_cart: '✅ Added {name} to cart!',
    char_added_services: '✅ Added {name} ({services}) to cart',
    char_pkg_name_upgrade_all: 'Max Upgrade — every cat in your save',
    char_pkg_name_unlock_all: 'Unlock every character in the game',
    char_pkg_name_trueform_all: 'True Form — every cat in your save',
    char_pkg_name_ultraform_all: 'Ultra Form — every cat in your save',
    char_pkg_name_talents_all: 'Max Talents — every cat in your save',
    char_manic_modal_warn_title: '⚠️ Requirements before purchase',
    char_manic_modal_warn_body: 'These 9 cats must be in your save file<br>and at <strong style="color:#FFD84E;">Lv. 30</strong> before doing True Form<br><br><span style="color:rgba(210,190,255,0.65);">Cat ID: <span style="color:#EDE6FF;font-family:monospace;">#91 #92 #93 #94 #95 #96 #97 #98 #99</span></span>',
    char_manic_modal_confirm_q: 'Are all 9 of your cats <strong style="color:#4ADE80;">already at Lv.30</strong>?',
    char_manic_modal_no_btn: '✕ Not Lv.30 yet',
    char_manic_modal_yes_btn: '✅ Lv.30 already, add to cart',
    char_ap_tw_info: 'Send an Angpao gift voucher matching the amount below, then paste the code/link in the box below',
    char_ap_upload_after: 'After transferring, upload your slip below',
    char_ap_paste_after: 'After transferring, paste the Angpao code/link below',
    char_ap_new_tc_send: 'New Transfer Code (send to customer)',
    char_ap_copied: '✅ Copied',
    char_ap_contact_price: 'Contact for price',

    // login.html
    login_subtitle: 'Member Account',
    login_tab_login: 'Log In',
    login_tab_register: 'Sign Up',
    login_username_label: 'Username',
    login_username_placeholder: 'Your username',
    login_password_label: 'Password',
    login_password_placeholder: 'Password',
    login_btn: '🔑 Log In',
    login_register_username_placeholder: 'At least 3 characters',
    login_register_password_placeholder: 'At least 6 characters',
    login_confirm_password_label: 'Confirm Password',
    login_confirm_password_placeholder: 'Password again',
    login_register_btn: '✨ Sign Up',
    login_back_link: '← Back to Home',
    login_checking_btn: 'Checking...',
    login_recaptcha_failed: 'reCAPTCHA failed, please try again',
    login_success_btn: '✅ Success! Redirecting...',
    login_password_mismatch: 'Passwords do not match',
    login_registering_btn: 'Signing up...',
    login_register_success_redirect: '✅ Registered! Taking you to the homepage...',
    login_register_success_login: '✅ Registered! Please log in',
  };

  var STATUS_LABEL_EN = {
    pending:      '⏳ Awaiting payment',
    paid:         '💳 Paid — processing',
    done:         '✅ Completed',
    expired:      '⌛ Expired',
    bcsfe_failed: '❌ Processing failed',
    cancelled:    '🚫 Cancelled',
    unknown:      '❓ Unknown status',
  };
  window.bcStatusLabel = function(status, thaiLabel) {
    return (getLang() === 'en' && STATUS_LABEL_EN[status] !== undefined) ? STATUS_LABEL_EN[status] : thaiLabel;
  };

  var EN_DICT = EN;

  function getLang() {
    return localStorage.getItem(STORAGE_KEY) || 'th';
  }

  function applyLang(lang) {
    document.documentElement.lang = (lang === 'en') ? 'en' : 'th';
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (lang === 'en' && EN[key] !== undefined) {
        if (el.getAttribute('data-i18n-orig') === null) {
          el.setAttribute('data-i18n-orig', el.innerHTML);
        }
        el.innerHTML = EN[key];
      } else {
        var orig = el.getAttribute('data-i18n-orig');
        if (orig !== null) el.innerHTML = orig;
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-placeholder');
      if (lang === 'en' && EN[key] !== undefined) {
        if (el.getAttribute('data-i18n-ph-orig') === null) {
          el.setAttribute('data-i18n-ph-orig', el.getAttribute('placeholder') || '');
        }
        el.setAttribute('placeholder', EN[key]);
      } else {
        var origPh = el.getAttribute('data-i18n-ph-orig');
        if (origPh !== null) el.setAttribute('placeholder', origPh);
      }
    });
  }

  function updateToggleLabel(btn, lang) {
    btn.textContent = (lang === 'en') ? '🇹🇭 ไทย' : '🇬🇧 EN';
  }

  function setLang(lang) {
    localStorage.setItem(STORAGE_KEY, lang);
    applyLang(lang);
    var btn = document.getElementById('bc-lang-toggle');
    if (btn) updateToggleLabel(btn, lang);
    document.dispatchEvent(new CustomEvent('bc-lang-changed', { detail: { lang: lang } }));
  }

  // ── Public helper for pages with JS-rendered dynamic content ──
  // bcT('key', 'ข้อความไทยเดิม') -> English text if lang=en and key exists, else the Thai fallback
  window.bcT = function (key, thaiFallback) {
    return (getLang() === 'en' && EN_DICT[key] !== undefined) ? EN_DICT[key] : thaiFallback;
  };
  window.bcLang = getLang;

  function injectToggle() {
    if (document.getElementById('bc-lang-toggle')) return;
    var nav = document.querySelector('.nav-container');
    var btn = document.createElement('button');
    btn.id = 'bc-lang-toggle';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Switch language');
    btn.style.cssText = [
      'background:rgba(124,58,237,0.18)',
      'border:1px solid rgba(124,58,237,0.45)', 'color:#EDE6FF',
      'border-radius:8px', 'padding:6px 11px', 'font-size:12px',
      'font-weight:700', 'cursor:pointer', "font-family:'Chakra Petch',sans-serif",
      'flex-shrink:0', 'white-space:nowrap',
    ].join(';');
    btn.addEventListener('click', function () {
      setLang(getLang() === 'en' ? 'th' : 'en');
    });
    if (!nav) {
      // หน้าที่ไม่มี navbar (เช่น login.html) — ลอยมุมขวาบนแทน
      btn.style.cssText += ';position:fixed;top:16px;right:16px;z-index:9999;';
      document.body.appendChild(btn);
      updateToggleLabel(btn, getLang());
      return;
    }
    var cart = nav.querySelector('.nav-cart');
    if (cart) {
      // ห่อ toggle + cart ไว้ใน wrapper เดียว เพื่อให้ nav-container ยังเห็นแค่
      // 2 flex children (hamburger / wrapper) เหมือนเดิม — กัน space-between
      // ดันตำแหน่ง cart ไปทับ logo ที่ลอย absolute กลางจอบนมือถือ
      var wrapper = document.createElement('div');
      wrapper.style.cssText = 'display:flex;align-items:center;gap:8px;flex-shrink:0;';
      cart.parentNode.insertBefore(wrapper, cart);
      wrapper.appendChild(btn);
      wrapper.appendChild(cart);
    } else {
      nav.appendChild(btn);
    }
    updateToggleLabel(btn, getLang());
  }

  function init() {
    injectToggle();
    applyLang(getLang());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
