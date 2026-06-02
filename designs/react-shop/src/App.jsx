import React, { useEffect, useMemo, useState } from 'react'

const countryOptions = [
  { value: '1', label: 'EN - International' },
  { value: '2', label: 'JP - Japan' },
  { value: '3', label: 'KR - Korea' },
  { value: '4', label: 'TW - Taiwan' },
]

const products = [
  { key: 'cat_food', category: 'Cat Food', icon: '🐱', tag: 'HOT', label: 'Cat Food x10,000', desc: 'เติม Cat Food 10,000 หน่วย', price: 10, amount: 10000, oldPrice: 30 },
  { key: 'cat_food', category: 'Cat Food', icon: '🐱', tag: 'HOT', label: 'Cat Food x20,000', desc: 'เติม Cat Food 20,000 หน่วย', price: 19, amount: 20000, oldPrice: 45 },
  { key: 'cat_food', category: 'Cat Food', icon: '🐱', label: 'Cat Food x30,000', desc: 'เติม Cat Food 30,000 หน่วย', price: 25, amount: 30000, oldPrice: 65 },
  { key: 'cat_food', category: 'Cat Food', icon: '🐱', tag: 'MEGA', label: 'Cat Food x45,000', desc: 'เติม Cat Food 45,000 หน่วย', price: 35, amount: 45000, oldPrice: 90 },
  { key: 'xp', category: 'XP', icon: '🧠', label: 'XP x99,999,999', desc: 'เพิ่ม XP จำนวนสูงสุดในครั้งเดียว', price: 25, amount: 99999999, oldPrice: 480 },
  { key: 'normal_ticket', category: 'Normal Ticket', icon: '🎫', tag: 'RARE', label: 'Normal Ticket x100', desc: 'โอกาสได้แมวดี', price: 10, amount: 100, oldPrice: 150 },
  { key: 'normal_ticket', category: 'Normal Ticket', icon: '🎫', tag: 'RARE', label: 'Normal Ticket x500', desc: 'ลุ้นแมวหายาก', price: 29, amount: 500, oldPrice: 400 },
  { key: 'normal_ticket', category: 'Normal Ticket', icon: '🎫', tag: 'SUPER', label: 'Normal Ticket x1000', desc: 'ปลอดภัยไม่โดนแบน', price: 49, amount: 1000, oldPrice: 520 },
  { key: 'normal_ticket', category: 'Normal Ticket', icon: '🎫', tag: 'MEGA', label: 'Normal Ticket x2999', desc: 'ลุ้น Super Rare 1 ตัว!', price: 99, amount: 2999, oldPrice: 850 },
]

const categories = ['Cat Food', 'XP', 'Normal Ticket']

function createToast(message, type = 'success') {
  return { id: `${Date.now()}-${Math.random()}`, message, type }
}

export default function App() {
  const [cart, setCart] = useState(() => JSON.parse(localStorage.getItem('react-shop-cart') || '[]'))
  const [theme, setTheme] = useState(() => localStorage.getItem('react-shop-theme') || 'dark')
  const [transferCode, setTransferCode] = useState('')
  const [confirmationCode, setConfirmationCode] = useState('')
  const [country, setCountry] = useState('1')
  const [toast, setToast] = useState(null)
  const [orderResult, setOrderResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    localStorage.setItem('react-shop-cart', JSON.stringify(cart))
  }, [cart])

  useEffect(() => {
    localStorage.setItem('react-shop-theme', theme)
    document.body.className = theme === 'light' ? 'light' : ''
  }, [theme])

  useEffect(() => {
    if (!toast) return
    const timeout = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(timeout)
  }, [toast])

  const groupedSections = useMemo(
    () => categories.map(category => ({ category, items: products.filter(item => item.category === category) })),
    []
  )

  const totalPrice = cart.reduce((sum, item) => sum + item.price, 0)

  function addToCart(product) {
    if (cart.some(item => item.label === product.label)) {
      setToast(createToast('รายการนี้อยู่ในตะกร้าแล้ว', 'error'))
      return
    }
    setCart([...cart, product])
    setToast(createToast(`${product.label} ถูกเพิ่มลงตะกร้าแล้ว`, 'success'))
  }

  function removeItem(label) {
    setCart(cart.filter(item => item.label !== label))
    setToast(createToast('ลบสินค้าออกจากตะกร้าแล้ว', 'success'))
  }

  async function checkout() {
    if (!cart.length) {
      setToast(createToast('กรุณาเลือกสินค้าอย่างน้อย 1 รายการ', 'error'))
      return
    }
    if (!transferCode || !confirmationCode) {
      setToast(createToast('กรอก Transfer และ Confirmation ให้ครบ', 'error'))
      return
    }

    setLoading(true)
    setOrderResult(null)

    try {
      const response = await fetch('/api/payment/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transfer_code: transferCode,
          confirmation_code: confirmationCode,
          country,
          items: cart.map(item => ({ key: item.key, amount: item.amount })),
        }),
      })

      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'เกิดข้อผิดพลาดจากเซิร์ฟเวอร์')
      setOrderResult(data)
      setToast(createToast('สร้างคำสั่งซื้อสำเร็จแล้ว', 'success'))
    } catch (error) {
      setToast(createToast(error.message, 'error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-root">
      <nav className="nav">
        <div className="nav-logo">🐱 BATTLE CATS SHOP</div>
        <div className="nav-actions">
          <button className="btn btn-secondary" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
            {theme === 'light' ? 'โหมดมืด' : 'โหมดสว่าง'}
          </button>
          <span className="cart-badge">{cart.length}</span>
        </div>
      </nav>

      <main className="page">
        <section className="hero">
          <h1 className="hero-title">Battle Cats Shop</h1>
          <p className="hero-sub">หน้าร้าน React พร้อมตะกร้าและการเชื่อมต่อ API สำหรับสร้างคำสั่งซื้อ</p>
        </section>

        <section className="grid grid-2">
          <div>
            {groupedSections.map(section => (
              <div key={section.category} className="section">
                <h2 className="section-title">{section.category}</h2>
                <div className="grid grid-2">
                  {section.items.map(item => (
                    <article key={item.label} className="card">
                      <div className="card-emoji">{item.icon}</div>
                      <h3 className="card-name">{item.label}</h3>
                      <p className="card-desc">{item.desc}</p>
                      <div className="card-price">
                        <span className="price-now">฿{item.price}</span>
                        <span className="price-old">฿{item.oldPrice}</span>
                      </div>
                      <button className="btn btn-primary" onClick={() => addToCart(item)}>
                        เพิ่มลงการ์ท
                      </button>
                    </article>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <aside className="summary-panel">
            <h2>สรุปตะกร้า</h2>
            {cart.length === 0 ? (
              <p className="hero-sub">ยังไม่มีสินค้าในตะกร้า</p>
            ) : (
              <ul className="summary-list">
                {cart.map(item => (
                  <li key={item.label} className="summary-item">
                    <strong>{item.label}</strong>
                    <span>{item.desc}</span>
                    <div className="price-row">
                      <span>{item.price} บาท</span>
                      <button className="btn btn-secondary" onClick={() => removeItem(item.label)}>
                        ลบ
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="summary-total">
              <strong>รวมทั้งหมด</strong>
              <strong>{totalPrice} บาท</strong>
            </div>

            <div className="checkout-panel">
              <div className="form-field">
                <label>Transfer Code</label>
                <input value={transferCode} onChange={e => setTransferCode(e.target.value)} placeholder="Transfer Code" />
              </div>
              <div className="form-field">
                <label>Confirmation Code</label>
                <input value={confirmationCode} onChange={e => setConfirmationCode(e.target.value)} placeholder="Confirmation Code" />
              </div>
              <div className="form-field">
                <label>Country</label>
                <select value={country} onChange={e => setCountry(e.target.value)}>
                  {countryOptions.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <button className="btn btn-primary" onClick={checkout} disabled={loading}>
                {loading ? 'กำลังสร้าง...' : 'สร้างคำสั่งซื้อ'}
              </button>
            </div>

            {orderResult ? (
              <div className="order-result">
                <h3>สร้าง order สำเร็จ</h3>
                <p>Order ID: <strong>{orderResult.order_id}</strong></p>
                <p>ยอดชำระ: <strong>{orderResult.amount} บาท</strong></p>
                <div className="order-qr">
                  <img src={`data:image/png;base64,${orderResult.qr_base64}`} alt="PromptPay QR" />
                </div>
              </div>
            ) : null}
          </aside>
        </section>
      </main>

      {toast ? (
        <div className={`toast ${toast.type}`}>
          <span>{toast.type === 'success' ? '✅' : '⚠️'}</span>
          <span>{toast.message}</span>
        </div>
      ) : null}
    </div>
  )
}
