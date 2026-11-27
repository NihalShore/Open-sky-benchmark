/**
 * NESTED HEALPix ang2pix for the IRSA SPHEREx HiPS Norder 5 grid.
 * Adapted from the checked implementation in the supplied TimeLens engineering reference.
 */
export const HIPS_ORDER=5;
export const HIPS_NSIDE=1<<HIPS_ORDER;
export const HIPS_MAX_TILE=12*HIPS_NSIDE*HIPS_NSIDE-1;
function spreadBits(value){let out=0;for(let bit=0;bit<16;bit++)out|=((value>>bit)&1)<<(2*bit);return out;}
export function raDecToHipsTile(raDeg,decDeg,nside=HIPS_NSIDE){
 if(!Number.isFinite(raDeg)||!Number.isFinite(decDeg))throw new TypeError("Coordinates must be finite numbers.");
 if(!Number.isInteger(nside)||nside<1||(nside&(nside-1))!==0||nside>32768)throw new RangeError("HEALPix nside must be a supported power of two.");
 if(decDeg< -90||decDeg>90)throw new RangeError("Declination must be between -90 and 90 degrees.");
 const ra=((raDeg%360)+360)%360,z=Math.sin(decDeg*Math.PI/180),za=Math.abs(z),tt=ra/90;
 let face,ix,iy;
 if(za<=2/3){
  const temp1=nside*(.5+tt),temp2=nside*z*.75,jp=Math.floor(temp1-temp2),jm=Math.floor(temp1+temp2);
  const ifp=Math.floor(jp/nside),ifm=Math.floor(jm/nside);
  if(ifp===ifm)face=(ifp&3)|4;else if(ifp<ifm)face=ifp&3;else face=(ifm&3)+8;
  ix=jm&(nside-1);iy=nside-(jp&(nside-1))-1;
 }else{
  const ntt=Math.min(Math.floor(tt),3),tp=tt-ntt,tmp=nside*Math.sqrt(3*(1-za));
  const jp=Math.min(Math.floor(tp*tmp),nside-1),jm=Math.min(Math.floor((1-tp)*tmp),nside-1);
  if(z>=0){face=ntt;ix=nside-jm-1;iy=nside-jp-1;}else{face=ntt+8;ix=jp;iy=jm;}
 }
 return face*nside*nside+spreadBits(ix)+2*spreadBits(iy);
}
