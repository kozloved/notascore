
export async function getJob(id:string){
  const r=await fetch(`http://localhost:8000/job/${id}`)
  return r.json()
}
