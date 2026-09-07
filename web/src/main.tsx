import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

type Product={id:string;aoi_name:string;recipe:string;status:'draft'|'approved'|'published';accuracy?:{metric:string;value:number};drift?:{flagged:boolean};geometry:{type:string;coordinates:unknown};model_name:string;model_version:string;scene_ids:string[];processed_at:string;cloud_threshold:number};
const DEFAULT_API=location.hostname==='localhost'?'http://localhost:8081':'https://eop-peach.vercel.app';
const API=sessionStorage.api||import.meta.env.VITE_API_URL||DEFAULT_API;

function App(){
 const [token,setToken]=useState(sessionStorage.token||''); const [tenant,setTenant]=useState(sessionStorage.tenant||'');
 const [apiUrl,setApiUrl]=useState(sessionStorage.api||DEFAULT_API);
 const [products,setProducts]=useState<Product[]>([]); const [selected,setSelected]=useState<Product>(); const mapNode=useRef<HTMLDivElement>(null); const map=useRef<maplibregl.Map|null>(null);
 async function request(path:string,init?:RequestInit){const r=await fetch(API+path,{...init,headers:{'content-type':'application/json',authorization:`Bearer ${token}`,'x-tenant-id':tenant,...init?.headers}});if(!r.ok)throw new Error(await r.text());return r.json()}
 async function refresh(){if(token&&tenant)setProducts(await request('/api/products'))}
 useEffect(()=>{refresh().catch(console.error)},[token,tenant]);
 useEffect(()=>{if(!mapNode.current||map.current)return;map.current=new maplibregl.Map({container:mapNode.current,style:'https://demotiles.maplibre.org/style.json',center:[178,-17],zoom:4})},[]);
 useEffect(()=>{const m=map.current;if(!m)return;const data={type:'FeatureCollection' as const,features:products.map(p=>({type:'Feature' as const,geometry:p.geometry,properties:{id:p.id,status:p.status}}))};const update=()=>{if(m.getSource('products'))(m.getSource('products') as maplibregl.GeoJSONSource).setData(data as never);else{m.addSource('products',{type:'geojson',data:data as never});m.addLayer({id:'products-fill',type:'fill',source:'products',paint:{'fill-color':['match',['get','status'],'draft','#f59e0b','approved','#38bdf8','#16a34a'],'fill-opacity':.42}})}};m.loaded()?update():m.once('load',update)},[products]);
 async function action(id:string,verb:'approve'|'publish'){await request(`/api/products/${id}/${verb}`,{method:'POST',body:verb==='approve'?JSON.stringify({comment:'Approved in PacificEO dashboard'}):undefined});await refresh()}
 if(!token||!tenant)return <main className="login"><h1>PacificEO Monitor</h1><p>Secure tenant workspace</p><input aria-label="Docker API URL" value={apiUrl} onChange={e=>setApiUrl(e.target.value)} placeholder="Docker API URL"/><input aria-label="Supabase access token" placeholder="Supabase access token" onChange={e=>setToken(e.target.value)}/><input aria-label="Tenant UUID" placeholder="Tenant UUID" onChange={e=>setTenant(e.target.value)}/><button onClick={()=>{sessionStorage.api=apiUrl.replace(/\/$/,'');sessionStorage.token=token;sessionStorage.tenant=tenant;location.reload()}}>Enter</button></main>;
 const queue=products.filter(p=>p.status!=='published');
 return <main><header><div><span className="eyebrow">Viti Waitui</span><h1>PacificEO Monitor</h1></div><button className="quiet" onClick={()=>{sessionStorage.clear();location.reload()}}>Sign out</button></header><section className="layout"><div className="map" ref={mapNode}/><aside><h2>Review queue <b>{queue.length}</b></h2>{queue.map(p=><article key={p.id} onClick={()=>setSelected(p)}><span className={`status ${p.status}`}>{p.status}</span><h3>{p.aoi_name}</h3><p>{p.recipe}</p><small>{p.accuracy?`${p.accuracy.metric}: ${(p.accuracy.value*100).toFixed(1)}%`:'Accuracy not assessed'}</small><div>{p.status==='draft'&&<button onClick={e=>{e.stopPropagation();action(p.id,'approve')}}>Approve</button>}{p.status==='approved'&&<button onClick={e=>{e.stopPropagation();action(p.id,'publish')}}>Publish</button>}</div></article>)}</aside>{selected&&<section className="provenance"><button className="close" onClick={()=>setSelected(undefined)}>×</button><span className="eyebrow">Provenance</span><h2>{selected.recipe}</h2><dl><dt>Model</dt><dd>{selected.model_name}<br/>{selected.model_version}</dd><dt>Scenes</dt><dd>{selected.scene_ids.join(', ')}</dd><dt>Cloud gate</dt><dd>{selected.cloud_threshold}%</dd><dt>Processed</dt><dd>{new Date(selected.processed_at).toLocaleString()}</dd><dt>Validation</dt><dd>{selected.accuracy?`${selected.accuracy.metric}: ${selected.accuracy.value}`:'Not assessed'}</dd><dt>Drift</dt><dd>{selected.drift?.flagged?'Flagged for review':'No flag'}</dd></dl></section>}</section></main>
}
createRoot(document.getElementById('root')!).render(<App/>);
