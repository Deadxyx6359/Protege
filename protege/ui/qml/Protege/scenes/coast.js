.pragma library
.import "pixel.js" as P
.import "world.js" as World

// Driftwood Bay. These contours and placements are authored as one scene.
// Seeds add small material marks, never decide where land or a subject lives.
var SHORE = [[0,165],[35,172],[68,186],[107,196],[147,200],[181,204],
             [219,219],[262,229],[302,232],[343,225],[390,211],[436,200],[480,193]];
// The left mountain must end inside its wooded headland. Its old foot at
// (269,139) projected beyond the shore and hung over the open channel.
var FAR_LEFT = [[0,135],[45,128],[68,116],[85,112],[100,126],[128,127],
                [153,139],[192,141],[224,137],[244,142],[256,146]];
var FAR_RIGHT = [[303,146],[329,134],[350,137],[371,129],[405,133],
                 [432,122],[458,128],[480,126]];
function shore(x) { return P.contour(SHORE, x); }
function ground(x) { return shore(x) + 13 + 3 * Math.sin(x * 0.043); }

function pine(p, x, base, h, colors, lean, snow, shadow) {
    /*  Every other object casts a shadow; the pines did not, which left them
        looking pasted onto the meadow. Note that ellipse() takes *radii* — an
        earlier attempt passed h*0.30 as a width and painted a sixty-pixel dark
        blob under every tree.  */
    if(shadow) p.ellipse(x-h*0.08,base,h*0.24,2,shadow);
    p.line(x,base,x+lean*0.3,base-h*0.82,colors[0],Math.max(1,h/35));
    for(var row=0;row<h*0.90;row++) {
        var t=row/h, tier=(row/(h*0.115))%1;
        var half=h*0.29*t*(0.50+tier*0.64);
        var centre=x+lean*Math.pow(1-t,2);
        for(var dx=Math.ceil(-half);dx<=Math.floor(half);dx++) {
            var fleck=P.hash(Math.floor(dx/3)*117+Math.floor(row/2)*37+x);
            // Sun at x=324: the right of each tier catches the light.
            var index=dx>half*0.14?1:0;
            if(dx>0 && fleck>0.78 && tier>0.5) index=2;
            var col=snow && tier<0.23 && dx>-half*0.45?snow:colors[index];
            p.dot(centre+dx,base-h+row,col);
        }
    }
}

function oak(p, x, base, h, pal, lean, season) {
    p.ellipse(x-7,base+1,h*0.36,3,pal.shadow);
    var crown = base-h*0.66;
    p.poly([[x-4,base],[x+4,base],[x+2+lean*0.25,crown],[x-2+lean*0.25,crown]],pal.bark);
    p.line(x+2,base-1,x+3+lean*0.25,crown,pal.barkLight);
    var clusters = [[-0.27,0.07,0.19],[-0.12,-0.16,0.21],[0.07,-0.23,0.22],
                    [0.28,-0.10,0.18],[0.32,0.10,0.20],[0.04,0.08,0.27],[-0.20,0.19,0.18]];
    for(var branch=0;branch<clusters.length;branch++) {
        var br=clusters[branch];
        p.line(x,crown+19,x+br[0]*h+lean,crown+br[1]*h+6,pal.bark,2);
    }
    // Union of irregular lobes, shaded as one crown. Coarse clusters of leaves
    // interrupt edges and light planes without a polka-dot or bubble outline.
    for(var py=-h*0.46;py<h*0.39;py++) {
        for(var px=-h*0.51;px<h*0.55;px++) {
            var closest=4, lobeY=0, lobeX=0;
            for(var b=0;b<clusters.length;b++) {
                var q=clusters[b], dx=(px-q[0]*h)/(q[2]*h), dy=(py-q[1]*h)/(q[2]*h*0.76);
                var distance=dx*dx+dy*dy;
                if(distance<closest) { closest=distance;lobeY=dy;lobeX=dx; }
            }
            var noise=P.hash(Math.floor(px/3)*57+Math.floor(py/2)*317+873);
            if(closest>0.90+noise*0.22) continue;
            // +lobeX, not -: the crown is lit from the upper right.
            var light=-lobeY*0.55+lobeX*0.18+noise*0.36;
            var col=pal.leaf[light>0.52?2:light>-0.06?1:0];
            if(season==="winter" && light>0.36) col=pal.snow;
            p.dot(x+px+lean,crown+py,col);
        }
    }
}

function cloud(p, x, y, scale, light, shadow, frame) {
    x += [0,1,1,0][frame];
    var shapes=[[-21,3,19,5],[-10,-1,16,7],[5,-4,15,8],[21,1,17,6],[32,4,11,3]];
    for(var i=0;i<shapes.length;i++) {
        var a=shapes[i]; p.ellipse(x+a[0]*scale,y+a[1]*scale,a[2]*scale,a[3]*scale,shadow);
    }
    for(var j=0;j<4;j++) {
        // Highlight rides the upper-right shoulder of each puff.
        var b=shapes[j]; p.ellipse(x+(b[0]+2)*scale,y+(b[1]-2)*scale,b[2]*scale*0.85,b[3]*scale*0.68,light);
    }
}

function cabin(p,x,y,c,winter,night) {
    /*  Rebuilt. The previous roof was a four-point quad whose right vertex sat
        beyond the wall while its bottom edge stepped between two heights, with
        a highlight stroke drawn a pixel clear of the surface and a chimney
        whose base stopped above the tiles. It read as three unrelated shapes
        floating over the house.

        A symmetric gable is the shape that reads at 28 pixels wide: one
        triangle, one fascia, a ridge highlight on the sunward slope, and a
        chimney sunk far enough into the roof to be part of it.  */
    var eaveY=y-17, apexY=y-31, apexX=x+14, leftEave=x-5, rightEave=x+33;

    p.ellipse(x+9,y+1,21,3,c.shadow);
    p.rect(x,y-16,28,17,c.wood);
    for(var i=0;i<5;i++) p.rect(x,y-14+i*3,28,1,c.bark);

    // Chimney first, so the roof laps over its base instead of the other way.
    p.rect(x+21,apexY-1,4,11,c.bark);
    p.rect(x+20,apexY-2,6,2,P.mix(c.bark,c.rockLight,0.42));

    // Gable: shaded slope left of the ridge, sunlit slope right of it.
    p.poly([[leftEave,eaveY],[apexX,apexY],[apexX,eaveY]],c.roof);
    p.poly([[apexX,apexY],[rightEave,eaveY],[apexX,eaveY]],
           P.mix(c.roof,c.roofLight,winter?0.5:0.62));
    p.line(apexX,apexY,apexX,eaveY,P.mix(c.roof,c.bark,0.45));
    p.line(apexX,apexY,rightEave,eaveY,winter?c.snow:P.mix(c.roofLight,c.cream,0.35),1);
    if(winter) p.line(leftEave,eaveY,apexX,apexY,c.snow,1);

    // Fascia: the roof's bottom edge, wider than the wall on both sides.
    p.rect(leftEave,eaveY,rightEave-leftEave,2,c.bark);

    p.rect(x+11,y-9,6,10,c.shadow);
    p.rect(x+4,y-11,5,5,night||winter?"#efbb79":c.window);
    p.rect(x+19,y-11,5,5,night||winter?"#efbb79":c.window);
    p.rect(x+6,y-11,1,5,c.wood); p.rect(x+4,y-9,5,1,c.wood);
    p.rect(x+21,y-11,1,5,c.wood); p.rect(x+19,y-9,5,1,c.wood);
    p.rect(x-2,y+1,31,2,P.mix(c.rockLight,c.shadow,0.35));
    if(winter) {
        for(var j=0;j<9;j++) p.dot(x+j*3+1,eaveY+2,["#e9bb7d","#acb9a1","#c67d72"][j%3]);
        p.ellipse(x+14,y-7,2,2,c.pine[1]); p.dot(x+14,y-5,"#c67d72");
    }
}

function parasol(p,x,base,c,red,folded) {
    p.ellipse(x-4,base,10,2,c.sandShadow);
    p.line(x,base,x,base-17,c.wood);
    if(folded) {
        p.poly([[x,base-19],[x-2,base-7],[x+2,base-7]],red);
        p.rect(x-2,base-9,4,1,c.cream);
        return;
    }
    p.poly([[x-11,base-10],[x-6,base-16],[x,base-19],[x+7,base-16],[x+12,base-10]],red);
    p.poly([[x-4,base-10],[x-2,base-16],[x,base-19],[x+4,base-10]],c.cream);
    p.line(x-11,base-10,x+12,base-10,c.sandShadow);
    p.rect(x+5,base-2,8,2,c.cream);
}

function paint(ctx,opts) {
    var p=new P.Painter(ctx), f=opts.frame||0, s=opts.season, winter=s==="winter";
    var wx=World.conditions(World.normaliseWeather(opts.weather));
    var n=World.nightness(opts.fraction), sky=World.sky(opts.fraction);
    var dusk=Math.max(0,1-Math.abs(opts.fraction-0.77)*19);
    function lit(c) { return P.mix(P.mix(c,"#e6ba92",dusk*0.18),"#182b43",n*0.72); }
    function tone(c) { return P.mix(lit(c),"#354d5b",wx.gloom*0.65); }
    var leaves=s==="spring"?["#79687f","#c693a8","#eed0d2"]:
               s==="autumn"?["#704b42","#af7043","#d7a765"]:
               winter?["#526774","#8b9eaa","#c6d4da"]:["#254d43","#427760","#78a071"];
    var c={leaf:leaves.map(tone),pine:[tone("#193e3c"),tone("#356258"),tone("#608873")],
        bark:tone("#4b4241"),barkLight:tone("#7d6954"),shadow:tone(winter?"#a0b8c9":"#344f43"),
        grass:tone(winter?"#dce5e4":s==="autumn"?"#9d9c63":"#789773"),
        grassLight:tone(winter?"#edf0e5":s==="autumn"?"#c1b47d":"#a5b98b"),
        grassDark:tone(winter?"#b7cccf":s==="autumn"?"#787d54":"#536f56"),
        sand:tone(winter?"#d2dadd":"#ddcba7"),sandShadow:tone(winter?"#aabcc6":"#aeac95"),
        foam:tone("#dbe9d8"),snow:tone("#edf0e9"),rock:tone("#596f6f"),rockLight:tone("#8b9c90"),
        wood:tone("#9a7760"),roof:tone("#445a61"),roofLight:tone("#849294"),window:tone("#a4c2bf"),cream:tone("#e7dcca")};
    var skyTop=P.mix(sky.top,"#465762",wx.gloom*0.85), skyBottom=P.mix(sky.bottom,"#889a9f",wx.gloom*0.78);
    // A limited ramp keeps the sky calm without conspicuous horizontal bands.
    for(var y=0;y<146;y++) {
        var t=Math.floor(y/4)/36;
        p.rect(0,y,480,1,P.mix(skyTop,skyBottom,t));
    }
    if(n>0.3 && wx.gloom<0.45) for(var st=0;st<85;st++) {
        var sx=Math.floor(P.hash(st+44)*480), sy=Math.floor(P.hash(st+93)*105);
        p.dot(sx,sy,P.mix(skyTop,"#e5e8da",0.3+P.hash(st)*n*0.5));
    }
    var sunX=324, sunY=48+Math.round(dusk*20);
    if(wx.gloom<0.45) {
        p.ellipse(sunX,sunY,15,15,P.mix(skyBottom,n>0.4?"#dce7de":"#f5e6be",0.35));
        p.ellipse(sunX,sunY,11,11,n>0.4?"#d6e1d8":"#f4e7c3");
        if(n>0.4) {p.ellipse(sunX+5,sunY-3,10,10,P.mix(skyTop,skyBottom,0.25));}
    }
    var cl=tone("#f0eadc"), cs=P.mix(skyBottom,tone("#94b0b8"),0.48);
    cloud(p,64,36,1.1,cl,cs,f); cloud(p,398,39,0.9,cl,cs,f);
    cloud(p,245,92,0.60,P.mix(cl,skyBottom,0.2),cs,f);
    cloud(p,454,86,0.65,cl,cs,f);
    if(wx.cover>4) {
        cloud(p,172,19,1.8,P.mix(cl,cs,0.65),cs,f);
        cloud(p,359,13,1.7,P.mix(cl,cs,0.7),cs,f);
        cloud(p,63,83,1.4,P.mix(cl,cs,0.7),cs,f);
    }
    if(wx.gloom>0.38) {
        var stormLight=P.mix(cs,tone("#718893"),0.65), stormShade=tone("#526b7a");
        cloud(p,23,12,2.6,stormLight,stormShade,f);
        cloud(p,188,16,2.4,stormLight,stormShade,f);
        cloud(p,388,14,2.8,stormLight,stormShade,f);
        cloud(p,458,62,1.7,stormLight,stormShade,f);
    }
    if(opts.lightning && wx.lightning>0) {
        var bolt=[[415,46],[411,57],[415,56],[404,71],[407,70],[398,88]];
        for(var flash=0;flash<bolt.length-1;flash++) {
            var ba=bolt[flash],bb=bolt[flash+1];
            p.line(ba[0],ba[1],bb[0],bb[1],"#9fbdc3",2);
            p.line(ba[0],ba[1],bb[0],bb[1],"#d2e0d8");
        }
        p.line(405,70,399,68,"#9fbdc3");p.line(399,68,396,61,"#9fbdc3");
    }
    // Far ridges, one shared atmosphere for rock, snow, and their tree line.
    var far=P.mix(skyBottom,tone("#6c819a"),0.42);
    p.poly([[0,113],[28,95],[43,101],[76,70],[101,88],[122,66],[145,81],[169,94],
            [192,101],[225,116],[265,99],[290,106],[331,78],[347,91],[378,95],[408,77],[441,102],[480,95],[480,148],[0,148]],far);
    var ridge=tone("#7e96a4"), shade=tone("#607c92"), snow=P.mix(tone("#e0e8dc"),skyBottom,0.23);
    /*  With the sun to the right, the whole left flank is the shadow side and
        only the faces turned toward it are lit. The body therefore carries the
        shadow tone and the right-hand face is painted back in.  */
    var litFace=P.mix(ridge,snow,0.26);
    p.poly([[0,133],[26,115],[54,117],[88,85],[106,90],[146,48],[163,65],[174,63],
            [197,91],[215,110],[229,122],[238,134],[247,144],[0,146]],shade);
    p.poly([[146,48],[155,76],[174,103],[201,118],[219,109],[197,91],[174,63],[163,65]],litFace);
    p.poly([[146,48],[121,74],[133,70],[140,78],[146,64],[153,76],[158,75]],P.mix(snow,shade,0.42));
    p.poly([[174,63],[159,77],[171,75],[175,84],[184,78]],P.mix(snow,litFace,0.18));
    p.poly([[88,85],[76,98],[87,94],[94,99],[106,90]],P.mix(snow,shade,0.5));
    // Broad facets follow the slope; no unrelated dots masquerading as rocks.
    p.poly([[139,82],[110,108],[90,118],[73,135],[107,127],[127,111]],P.mix(shade,ridge,0.30));
    p.poly([[153,91],[177,126],[206,137],[182,130],[170,112]],P.mix(litFace,ridge,0.35));
    // Eroded ledges and snow gullies follow the authored mountain faces.
    var faceLight=P.mix(shade,ridge,0.48), faceDark=P.mix(shade,"#4a6076",0.30);
    for(var ledge=0;ledge<90;ledge++) {
        var ly=78+P.hash(ledge*3+263)*47;
        var lx=146-(ly-48)*0.69+P.hash(ledge*7+426)*(ly-48)*0.76;
        p.line(lx,ly,lx-2-P.hash(ledge)*5,ly+2,ledge%3===0?faceLight:faceDark);
    }
    p.poly([[141,74],[135,89],[128,96],[134,91],[138,87],[137,85]],P.mix(snow,shade,0.46));
    p.poly([[174,86],[182,101],[181,104],[190,114],[186,103]],P.mix(litFace,ridge,0.5));
    /*  Distance desaturates toward the sky, which is why these stay blue-
        green — but a wholly teal far shore under an autumn oak read as two
        different times of year in one frame. A fifth of the season's leaf
        colour is enough to agree without breaking the aerial perspective.  */
    var farLeaf=P.mix("#000000",leaves[1],1), farTint=s==="summer"?0.10:0.22;
    p.poly(FAR_LEFT.concat([[256,151],[0,151]]),P.mix(tone("#6a8d91"),tone(farLeaf),farTint));
    p.poly(FAR_RIGHT.concat([[480,151],[303,151]]),P.mix(tone("#799797"),tone(farLeaf),farTint));
    for(var tr=0;tr<190;tr++) {
        var tx=tr*2.6+P.hash(tr)*2, left=tx<256;
        if(tx>252 && tx<306) continue;
        var gy=P.contour(left?FAR_LEFT:FAR_RIGHT,tx)+3;
        var ht=3+P.hash(tr+551)*6;
        var tc=P.mix(tone(left?"#638787":"#718f90"),tone(farLeaf),farTint);
        p.poly([[tx,gy-ht],[tx-1,gy-ht*0.5],[tx-ht*0.34,gy],[tx+ht*0.35,gy]],tc);
    }
    // Sea occupies the complete bay; all beach and foliage are painted over it.
    var seaTop=tone("#66999f"), seaBottom=tone("#447e86");
    for(var wy=146;wy<270;wy++) p.rect(0,wy,480,1,P.mix(seaTop,seaBottom,Math.floor((wy-146)/9)/13));
    p.rect(0,146,480,1,P.mix(skyBottom,seaTop,0.5));
    for(var wave=0;wave<560;wave++) {
        var yy=148+P.hash(wave*7+244)*90, xx=P.hash(wave*3+934)*480;
        if(yy>shore(xx)-2) continue;
        var perspective=(yy-145)/90, ww=2+P.hash(wave+49)*12*perspective;
        xx += [0,1,2,1][f]*(1+wx.wind*2);
        var light=P.hash(wave+28)>0.58, wc=light?P.mix(seaTop,c.foam,0.28+wx.wind*0.15):P.mix(seaBottom,seaTop,0.45);
        if(Math.abs(xx-sunX)<8+perspective*44 && light && wx.gloom<0.4) wc=P.mix(wc,c.cream,0.45);
        p.rect(xx,yy,ww,1,wc);
        if(wx.wind>0.6 && wave%8===0) {
            p.line(xx,yy,xx+ww*0.6,yy-1,c.foam);
            p.rect(xx+ww*0.6,yy-2,2,1,c.foam);
            p.line(xx+ww*0.6+2,yy-1,xx+ww+3,yy,P.mix(c.foam,seaTop,0.25));
        }
    }
    // Beach, wrack line and dunes share the exact same shoreline function.
    for(var bx=0;bx<480;bx++) {
        var edge=shore(bx), earth=ground(bx);
        p.rect(bx,edge,1,270-edge,c.sandShadow);
        p.rect(bx,edge+4,1,270-edge,c.sand);
        p.rect(bx,earth,1,270-earth,c.grass);
        p.rect(bx,earth+1,1,1,c.grassLight);
        var swell=[0,1,2,1][f], foamY=edge-3-swell+Math.sin(bx*0.1+f*Math.PI/2)*1.2;
        if(P.hash(Math.floor(bx/5)+22)>0.16) p.rect(bx,foamY,1,wx.wind>0.6?2:1,c.foam);
    }
    // A low grassy bluff anchors the left forest to the coast.
    p.poly([[0,151],[31,158],[47,168],[65,183],[91,195],[113,202],[133,216],[0,237]],c.grassDark);
    p.poly([[0,151],[30,158],[48,169],[64,184],[90,195],[109,201],[100,205],[72,198],[43,181],[0,170]],c.grass);
    // Meadow brushwork lies in clusters and follows the slope into the foreground.
    for(var m=0;m<1000;m++) {
        var mx=P.hash(m*13+2001)*480, my=ground(mx)+P.hash(m*19+504)*(271-ground(mx));
        var cluster=Math.sin(mx*0.08+my*0.15)+Math.cos(mx*0.026-my*0.10);
        if(cluster<0.25) continue;
        p.rect(mx,my,2+P.hash(m+66)*6,1,m%3===0?c.grassLight:c.grassDark);
        if(m%11===0) p.line(mx,my,mx-1,my-3,c.grassDark);
    }
    // Winding path reaches the cottage steps, with its width increasing nearby.
    p.poly([[118,217],[122,222],[116,229],[119,235],[135,245],[146,254],[148,270],
            [132,270],[133,256],[124,248],[110,238],[109,230],[116,222]],c.sandShadow);
    p.poly([[118,217],[120,222],[113,231],[115,237],[130,247],[139,258],[139,270],
            [134,270],[135,258],[125,249],[111,238],[111,230],[116,222]],c.sand);
    cabin(p,104,220,c,winter,n>0.2||wx.gloom>0.4);
    // Distant boathouse and a moored skiff give the water a human scale.
    if(wx.wind<0.6) {
        p.line(300,174,314,174,c.shadow); p.line(302,175,311,175,c.wood);
        p.line(306,173,306,164,c.cream);
        p.poly([[307,164],[307,172],[313,172]],c.cream);
    }
    for(var rock=0;rock<18;rock++) {
        var rx=187+P.hash(rock+785)*222, ry=shore(rx)+6+P.hash(rock+255)*5;
        p.ellipse(rx,ry,2+P.hash(rock)*2,1,c.sandShadow);
    }
    /*  Cast shadows are mixed halfway to the grass they fall on. The full
        shadow tone is a saturated blue-green: correct under the cottage, but
        under a pumpkin on olive meadow it reads as a painted dash rather than
        as shade.  */
    c.castShadow=P.mix(c.grassDark,c.shadow,0.55);
    var wind=wx.wind*(1+[0,0.55,1,0.55][f]*wx.gust), lean=wind*6;
    // Trees grow from the bluff, not the water or the mountain surface.
    pine(p,16,175,47,c.pine,lean*0.55,winter?c.snow:null,c.castShadow);
    pine(p,45,184,31,c.pine,lean*0.4,winter?c.snow:null,c.castShadow);
    pine(p,69,197,27,c.pine,lean*0.3,winter?c.snow:null,c.castShadow);
    oak(p,29,247,99,c,lean,s);
    pine(p,452,237,108,c.pine,lean,winter?c.snow:null,c.castShadow);
    pine(p,478,250,81,c.pine,lean*0.8,winter?c.snow:null,c.castShadow);
    pine(p,425,239,49,c.pine,lean*0.5,winter?c.snow:null,c.castShadow);
    // Foreground rocks and shrubs are rooted in the same meadow plane.
    // Shadow pools to the left of the boulder; the sunward face is its right.
    p.ellipse(372,251,18,4,c.castShadow);
    p.poly([[363,249],[367,238],[380,234],[393,242],[396,250]],c.rock);
    p.poly([[380,234],[393,242],[396,250],[386,248],[379,241]],winter?c.snow:c.rockLight);
    p.line(370,241,366,248,c.shadow);
    for(var bush=0;bush<15;bush++) {
        var ux=bush<8?bush*11:390+(bush-8)*15;
        p.ellipse(ux,270-P.hash(bush+234)*5,9+P.hash(bush)*7,5+P.hash(bush+40)*7,c.pine[0]);
        p.ellipse(ux+3,266-P.hash(bush+234)*5,6,3,winter?c.snow:c.pine[1]);
    }
    if(!winter) for(var flower=0;flower<100;flower++) {
        var fx=54+P.hash(flower*3+758)*351, fy=239+P.hash(flower*5+973)*29;
        if(fx>108 && fx<154 || fx>359 && fx<398) continue;
        if(s==="autumn" && fx>78 && fx<122 && fy<246) continue;
        if(Math.sin(fx*0.045+fy*0.1)<0.1) continue;
        p.line(fx,fy,fx+Math.round(wind),fy-3,c.grassDark);
        var fc=s==="autumn"?["#cfad79","#ae774c"]:["#ddd6c0","#bcb0cf","#c8bcdc"];
        p.rect(fx+Math.round(wind),fy-4,2,1,tone(fc[flower%fc.length]));
    }
    if(s==="summer") {
        parasol(p,253,238,c,tone("#b87569"),wx.wind>0.6);
        parasol(p,338,231,c,tone("#668f96"),wx.wind>0.6);
        // A quiet pair of gulls; only their wings change across the four frames.
        if(wx.wind<0.6) for(var bird=0;bird<2;bird++) {
            var gx=286+bird*15, gy=121+bird*5, wing=[-1,0,1,0][f];
            p.line(gx-3,gy+wing,gx,gy+1,c.cream);p.line(gx,gy+1,gx+3,gy+wing,c.cream);
        }
    } else if(s==="spring") {
        for(var rabbit=0;rabbit<2;rabbit++) {
            var qx=166+rabbit*17,qy=250+rabbit*5;
            p.ellipse(qx+2,qy+1,5,1,c.shadow);
            p.ellipse(qx,qy-2,4,3,c.cream);p.ellipse(qx+3,qy-5,2,2,c.cream);
            p.rect(qx+2,qy-10,1,4,c.cream);p.rect(qx+4,qy-9,1,3,c.cream);
            p.dot(qx+4,qy-5,c.bark);p.dot(qx-4,qy-2,c.snow);
        }
    } else if(s==="autumn") {
        /*  Radii again: a shadow of radius 5 is eleven pixels wide, and at
            eight pixels apart the five of them fused into one dark green bar
            lying across the patch like a fence rail. Narrower shadows, wider
            spacing, ribs instead of a single bright stripe, and a green stem
            rather than a dark brown nail.  */
        for(var pumpkin=0;pumpkin<5;pumpkin++) {
            var px=87+(pumpkin%3)*11, py=226+Math.floor(pumpkin/3)*8;
            var skin=tone("#c07a3a"), rind=tone("#94592b");
            // Wider than tall, or it reads as an apple.
            p.ellipse(px-1,py+1,4,1,c.castShadow);
            p.ellipse(px,py-2,5,3,rind);
            p.ellipse(px+1,py-2,4,3,skin);
            p.line(px-2,py-4,px-2,py,rind);
            p.line(px+2,py-4,px+2,py,rind);
            p.rect(px,py-6,1,2,tone("#55703c"));
        }
        p.line(203,250,203,231,c.bark);p.line(197,236,209,236,c.bark);
        p.poly([[200,233],[206,233],[207,242],[199,241]],tone("#736578"));
        p.ellipse(203,230,2,2,c.sand);p.rect(199,228,9,1,c.bark);p.rect(201,226,4,2,c.bark);
        // An almost-missed figure in the pine shadow. No jump scare or flashing eyes.
        if(n>0.35) {
            var hidden=P.mix(c.pine[0],c.pine[1],0.15);
            p.rect(435,219,2,9,hidden);p.ellipse(436,217,2,2,hidden);
            p.line(435,228,434,232,hidden);p.line(436,228,437,232,hidden);
        }
    } else {
        pine(p,157,239,24,c.pine,0,c.snow);
        for(var bulb=0;bulb<8;bulb++) p.dot(153+(bulb%3)*3,223+Math.floor(bulb/3)*4,["#dfbb79","#be8375","#a4c3b9"][bulb%3]);
        p.dot(157,214,"#f0cf94");
        p.ellipse(188,253,7,2,c.shadow);
        p.ellipse(186,248,6,5,c.grassDark);p.ellipse(185,247,5,4,c.snow);
        p.ellipse(186,241,4,3,c.grassDark);p.ellipse(185,240,3,3,c.snow);
        p.rect(182,237,8,1,c.bark);p.rect(184,234,4,3,c.bark);
        p.rect(183,244,6,1,tone("#b87569"));p.dot(187,240,c.bark);p.dot(189,242,tone("#cf9559"));
    }
    // Weather overlays are spatially coherent with the water and foliage.
    if(wx.precip>0) for(var column=0;column<Math.round(wx.precip*24);column++) {
        // Repeated 28-pixel columns advance seven pixels in each of four
        // frames. The wrap continues downward instead of rewinding the rain.
        var offset=P.hash(column*7+535)*28;
        for(var drop=0;drop<11;drop++) {
            var ay=(offset+f*7+drop*28)%308-15;
            var ax=(P.hash(column*3+412)*540-ay*wx.wind*0.3+540)%540-30;
            if(wx.precipKind==="snow") p.rect(ax,ay,column%4===0?2:1,1,P.mix(c.snow,skyBottom,column%3*0.18));
            else p.line(ax,ay,ax-wx.wind*3,ay+2+wx.precip*4,P.mix(skyBottom,c.foam,0.18));
        }
    }
    if(opts.weather==="fog" || opts.weather==="blizzard") {
        /*  Drifting horizontal banks. This previously called cloud() at scale
            2.2 with the same colour for light and shadow, which laid a row of
            pale overlapping circles across the bay — it read as soap bubbles
            on the water rather than as mist. Fog settles in flat layers, so
            that is what is drawn: streaks of varying length, thickest near the
            waterline, each drifting at its own rate.  */
        // A graded bank across the water, thickest where it meets the far
        // shore, then streaks over it for structure.
        var deep=opts.weather==="fog";
        for(var band=0;band<9;band++) {
            ctx.globalAlpha=(deep?0.13:0.07)*(1-band/11);
            p.rect(0,146+band*6,480,7,c.foam);
        }
        ctx.globalAlpha=deep?0.30:0.15;
        for(var fog=0;fog<52;fog++) {
            var fy=147+P.hash(fog*11+61)*74;
            var depth=(fy-147)/74;
            var fw=36+P.hash(fog*7+13)*130+depth*90;
            var fx=(P.hash(fog*3+5)*600+f*(3+fog%4)*(1+wx.wind*2))%660-110;
            p.rect(fx,fy,fw,1+Math.floor(P.hash(fog+91)*3+depth*2),c.foam);
        }
        ctx.globalAlpha=1;
    }
}
