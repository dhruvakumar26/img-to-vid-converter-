import React, { useState } from "react";
import axios from "axios";

const API_URL = process.env.REACT_APP_API_URL || "backendapp-excfgcb6d7ghcjf7.polandcentral-01.azurewebsites.net";
//if (!API_URL) {
//  throw new Error("Missing REACT_APP_API_URL");
//}
//const API_URL = "backendapp-excfgcb6d7ghcjf7.polandcentral-01.azurewebsites.net";

function App() {
  const [images, setImages] = useState([]);
  const [audio, setAudio] = useState(null);
  const [status, setStatus] = useState("");
  const [resultUrl, setResultUrl] = useState("");

  function handleImages(e) {
    const files = Array.from(e.target.files);
    setImages(prev => [...prev, ...files]);
  }

  function removeImage(index) {
    setImages(prev => prev.filter((_, i) => i !== index));
  }

  function moveImage(from, to) {
    const arr = [...images];
    if (to < 0 || to >= arr.length) return;
    const [item] = arr.splice(from, 1);
    arr.splice(to, 0, item);
    setImages(arr);
  }

  async function convert() {
    if (!images.length) return alert("Add images");
    const fd = new FormData();
    images.forEach((f) => fd.append("images", f));
    if (audio) fd.append("audio", audio);
    setStatus("Uploading...");
    try {
      const resp = await axios.post(`${API_URL}/api/convert`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const jobId = resp.data.job_id;
      setStatus("Processing...");
      pollStatus(jobId);
    } catch (e) {
      console.error(e);
      setStatus("Upload failed");
    }
  }

  async function pollStatus(id) {
    const interval = setInterval(async () => {
      try {
        const r = await axios.get(`${API_URL}/api/status/${id}`);
        setStatus(r.data.status);
        if (r.data.status === "done") {
          clearInterval(interval);
          setResultUrl(`${API_URL}/api/download/${id}`);
        } else if (r.data.status === "error") {
          clearInterval(interval);
        }
      } catch (e) {
        clearInterval(interval);
        setStatus("Error polling status");
      }
    }, 3000);
  }

  return (
    <div style={{ padding: 20, maxWidth: 800 }}>
      <h2>Image → Video converter</h2>
      <div>
        <input type="file" accept="image/*" multiple onChange={handleImages} />
        <div>
          {images.map((img, idx) => (
            <div key={idx}>
              {img.name}
              <button onClick={() => removeImage(idx)}>Remove</button>
              <button onClick={() => moveImage(idx, idx-1)}>↑</button>
              <button onClick={() => moveImage(idx, idx+1)}>↓</button>
            </div>
          ))}
        </div>
      </div>
      <div>
        <label>Audio: </label>
        <input type="file" accept="audio/*" onChange={(e) => setAudio(e.target.files[0])} />
      </div>
      <div style={{ marginTop: 10 }}>
        <button onClick={convert}>Convert</button>
      </div>
      <div style={{ marginTop: 10 }}>
        <strong>Status:</strong> {status}
      </div>
      {resultUrl && (
        <div>
          <a href={resultUrl} target="_blank" rel="noreferrer">Download result</a>
          <br/>
          <video src={resultUrl} controls style={{ maxWidth: 400 }} />
        </div>
      )}
    </div>
  );
}

export default App;