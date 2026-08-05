
'use client'
import { supabase } from '../lib/supabase'
export default function AuthButton(){
  async function login(){
    await supabase.auth.signInWithOAuth({ provider:'google' })
  }
  return <button onClick={login}>Continue with Google</button>
}
