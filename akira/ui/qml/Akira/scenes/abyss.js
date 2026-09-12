.pragma library
.import "pixel.js" as P

// The Drowned Archive. The quiet centre is open water; inhabited shelves frame
// a trench below it. Every organism, ruin and piece of equipment has a depth.
var FLOOR=[[0,235],[53,236],[95,252],[142,248],[181,261],[232,268],
           [280,259],[322,249],[351,232],[397,225],[433,234],[480,229]];
function ground(x) { return P.contour(FLOOR,x); }

function strand(p,points,color,width) {
    for(var i=0;i<points.length-1;i++)
        p.line(points[i][0],points[i][1],points[i+1][0],points[i+1][1],color,width||1);
}

function glow(p,x,y,rx,ry,color,strength) {
    // Nested pixel ellipses keep the halo on the same grid as the painting.
    // Only luminous organisms get this bloom; darkness between them matters.
    for(var ring=4;ring>=1;ring--) {
        p.ctx.globalAlpha=strength*(5-ring)/7;
        p.ellipse(x,y,rx*(1+ring*0.3),ry*(1+ring*0.3),color);
    }
    p.ctx.globalAlpha=1;
}

function glassSponge(p,x,y,h,r) {
    // Hollow, translucent silica baskets: an open rim, fine diamond lattice,
    // and a narrow fibre tuft fastening each one to its rock ledge.
    for(var row=0;row<h;row++) {
        var t=row/h,cx=x+Math.sin(t*2)*r*0.18,half=r*(0.58+0.42*(1-t)*(1-t));
        var left=Math.ceil(cx-half),right=Math.floor(cx+half),yy=y-h+row;
        p.dot(left,yy,"#456775");p.dot(right,yy,"#a0b8c9");
        for(var xx=left+1;xx<right;xx++) {
            if((xx+row)%7===0 || (xx-row+280)%7===0)
                p.dot(xx,yy,(xx+row)%7===0?"#688c9f":"#3a5b70");
        }
        if(row%9===0) p.line(left,yy,right,yy,"#426979");
    }
    p.ellipse(x,y-h,r,Math.max(1,r*0.32),"#819eaf");
    p.ellipse(x,y-h,r-2,Math.max(1,r*0.21),"#142d3a");
    p.line(x-r+2,y-h-1,x+1,y-h-2,"#b2c4d5");
    for(var fibre=-2;fibre<=2;fibre++) p.line(x+fibre,y-1,x+fibre*2,y+3,"#476b7a");
}

function frond(p,x,y,h,frame,seed) {
    var sway=[0,1,2,1][frame],previous=[x,y];
    for(var i=1;i<=7;i++) {
        var t=i/7,xx=x+Math.sin(t*4+seed)*3+t*t*sway,yy=y-h*t;
        p.line(previous[0],previous[1],xx,yy,"#235052");
        var side=i%2===0?1:-1;
        p.poly([[xx,yy+2],[xx+side*(4-t*2),yy-1],[xx+side*(5-t*3),yy-5],[xx+side,yy-1]],"#15393d");
        if(i>4) p.dot(xx+side,yy-2,"#306466");
        previous=[xx,yy];
    }
}

function jelly(p,x,y,r,frame,small) {
    var bob=[0,0,1,0][frame];y+=bob;
    var pulse=[0.15,0.18,0.20,0.18][frame];
    glow(p,x,y+2,r+3,r*1.3,small?"#7953ee":"#20c9eb",pulse);
    var outer=small?"#393668":"#175d7a",rim=small?"#b38aff":"#62fff2";
    p.ellipse(x,y,r+2,r*0.58,small?"#202346":"#113b56");
    p.ellipse(x,y,r,r*0.56,outer);
    p.ellipse(x,y-1,r-2,r*0.36,small?"#6c50a0":"#269ca8");
    p.line(x-r+1,y+2,x+r-1,y+2,rim);
    p.rect(x-2,y-2,4,1,small?"#e9b5ff":"#d0fff5");
    for(var t=0;t<4;t++) {
        var tx=x-r*0.6+t*r*0.4,swing=[0,1,0,-1][(frame+t)%4];
        strand(p,[[tx,y+3],[tx+swing,y+r],[tx-1,y+r*1.5],[tx+swing,y+r*2]],t%2===0?rim:outer);
        if(t%2===0) p.dot(tx+swing,y+r*2,small?"#df96fa":"#a7fff2");
    }
}

function shark(p,x,y,size,color,right) {
    var d=right?1:-1;
    function pts(points) { return points.map(function(q){return[x+q[0]*size*d,y+q[1]*size];}); }
    p.poly(pts([[-0.5,0],[-0.20,-0.12],[0.23,-0.1],[0.5,0],[0.19,0.11],[-0.23,0.10]]),color);
    p.poly(pts([[-0.05,-0.07],[0.04,-0.32],[0.17,-0.07]]),color);
    p.poly(pts([[-0.4,0],[-0.68,-0.23],[-0.61,0.02],[-0.69,0.19]]),color);
    p.poly(pts([[0.09,0.07],[-0.02,0.24],[0.26,0.08]]),color);
    p.line(x+size*0.22*d,y+1,x+size*0.42*d,y,"#25424c");
}

function leviathan(p) {
    // Large enough to imply scale, only a few values away from the water.
    // Its tail disappears behind the canyon wall painted in front of it.
    var body="#081a25",edge="#102733";
    p.poly([[239,139],[250,130],[274,128],[295,119],[324,111],[357,107],
            [388,111],[411,117],[438,112],[460,101],[451,119],[426,130],
            [400,130],[376,124],[349,126],[319,132],[291,145],[266,150],[247,146]],body);
    p.poly([[313,116],[326,98],[331,110],[346,111]],body);
    p.poly([[356,113],[369,99],[369,111],[382,115]],body);
    p.poly([[276,144],[284,158],[295,166],[287,153],[299,142]],body);
    strand(p,[[250,144],[243,147],[237,146],[233,143]],edge);
    strand(p,[[250,145],[248,153],[243,154],[240,151]],body);
    p.dot(251,136,"#345455");
    // A second, smaller eye and the long sensory filaments are the hint that
    // this is not simply a large shark. No flashing eyes or sudden appearance.
    p.dot(253,138,"#243f47");
    strand(p,[[258,145],[262,152],[260,164],[264,170],[268,168]],"#0e2430");
    strand(p,[[261,146],[266,151],[265,161],[269,166]],"#0d222d");
    for(var tooth=0;tooth<4;tooth++) p.dot(243+tooth*2,142+tooth%2,"#172d37");
    p.line(242,140,250,140,edge);
    for(var gill=0;gill<3;gill++) p.line(268+gill*4,134,266+gill*4,141,edge);
    var marks=[[284,130],[300,125],[319,119],[345,115],[372,116]];
    for(var i=0;i<marks.length;i++) p.dot(marks[i][0],marks[i][1],"#19323b");
}

function submersible(p,frame) {
    var x=102,y=78;
    glow(p,x+18,y+5,5,5,"#96d8cd",0.10);
    p.ellipse(x,y,20,9,"#071620");
    p.poly([[x-15,y-5],[x-9,y-9],[x+10,y-9],[x+17,y-4],[x+20,y+3],
            [x+12,y+7],[x-11,y+7],[x-17,y+2]],"#52615c");
    p.poly([[x-15,y-4],[x-9,y-8],[x+10,y-8],[x+17,y-3],[x+11,y-3],[x-11,y-2]],"#8b8a69");
    p.rect(x-13,y+2,27,3,"#263e43");
    p.rect(x-9,y-12,11,4,"#405653");p.rect(x-7,y-13,7,1,"#7d8270");
    p.line(x-3,y-13,x-3,y-18,"#37505a");p.line(x-3,y-18,x+3,y-18,"#37505a");
    p.rect(x-21,y-4,4,10,"#293e48");p.line(x-24,y-2,x-18,y+3,"#527078");
    p.ellipse(x+12,y-1,5,5,"#153842");p.ellipse(x+13,y-1,3,3,"#69abb0");
    p.dot(x+14,y-2,"#dafff0");
    for(var port=0;port<2;port++) {p.ellipse(x-9+port*8,y-2,2,2,"#172c37");p.dot(x-8+port*8,y-3,"#789c9d");}
    p.line(x-10,y+7,x-8,y+10,"#34515a");p.line(x-8,y+10,x+15,y+10,"#34515a");
    p.rect(x+17,y+4,3,2,["#c5eacb","#d7f5d4","#e5ffde","#d7f5d4"][frame]);
}

function temple(p,frame) {
    // Foundation is cut into the right shelf. The slab, not a floating sprite,
    // carries the columns; broken tops and asymmetric cracks expose its age.
    p.poly([[333,232],[350,219],[405,217],[431,227],[419,238],[352,243]],"#1b3339");
    p.poly([[350,219],[405,217],[421,223],[352,226],[333,232]],"#2b484a");
    p.rect(340,222,81,3,"#304c4d");p.rect(345,218,73,4,"#496366");
    p.rect(346,219,71,1,"#547675");
    p.rect(350,191,62,27,"#20383e");
    // Broken entablature: a fragment remains above the missing left column.
    p.poly([[347,187],[359,180],[370,182],[375,177],[401,181],[414,188],[413,192],[349,192]],"#3e595d");
    p.line(349,189,411,189,"#577275");
    p.line(359,184,371,184,"#24414a");p.line(372,181,370,187,"#1b333d");
    var columns=[[352,204],[364,192],[402,192]];
    for(var col=0;col<columns.length;col++) {
        var x=columns[col][0],top=columns[col][1];
        p.rect(x,top,5,26-(top-192),"#3a585b");p.rect(x+3,top,2,218-top,"#547074");
        p.rect(x-1,top-1,7,2,"#456266");p.rect(x-1,215,7,3,"#456266");
        p.line(x+1,top+4,x+1,213,"#2a454d");
    }
    // Door light is restrained, and blocked by the columns rather than leaking
    // across them. Its four-frame pulse stays below the animal highlights.
    p.poly([[375,217],[375,196],[379,191],[389,191],[394,197],[394,217]],"#0a222c");
    p.poly([[379,215],[379,198],[382,195],[387,195],[391,199],[391,215]],"#173a42");
    p.line(377,215,377,197,"#52787a");p.line(377,197,380,193,"#52787a");
    p.line(380,193,389,193,"#52787a");p.line(389,193,393,198,"#355961");
    glow(p,385,204,4,7,"#20a8b8",0.15);
    var glyph=["#55d9cf","#6eeadd","#91fff1","#6eeadd"][frame];
    strand(p,[[384,198],[387,201],[382,204],[387,207],[384,211]],glyph);
    p.dot(385,200,"#c3ffef");
    p.poly([[379,216],[391,216],[399,223],[371,223]],"#316465");
    p.line(375,220,394,220,"#539a8e");p.line(372,224,401,224,"#2e6564");
    // Settled rubble, fragments of inscriptions and growth in masonry joints.
    strand(p,[[395,193],[399,198],[397,206],[401,211]],"#132d36");
    p.rect(358,197,3,1,"#4d6666");p.rect(358,201,2,1,"#39555c");
    p.poly([[346,215],[349,209],[354,210],[357,216]],"#3e555a");
    p.line(347,212,351,210,"#607577");
    for(var moss=0;moss<16;moss++) {
        var mx=349+P.hash(moss*7+214)*62,my=190+P.hash(moss*11+45)*3;
        p.rect(mx,my,2,1,"#2c5555");
    }
}

function paint(ctx,frame) {
    var p=new P.Painter(ctx),f=frame||0;
    for(var y=0;y<270;y++) p.rect(0,y,480,1,P.mix("#030d19","#0a202b",Math.floor(y/8)/34));
    // Absorption takes the searchlight gradually into darkness: a hard-ended
    // triangle would look like a solid object suspended in the trench.
    for(var beamY=84;beamY<248;beamY++) {
        var distance=beamY-83,centre=120+distance*0.53;
        ctx.globalAlpha=0.095*Math.pow(1-distance/166,1.1);
        for(var cone=0;cone<5;cone++) {
            var half=distance*(0.30-cone*0.052);
            p.rect(centre-half,beamY,half*2,1,"#83b3b0");
        }
    }
    ctx.globalAlpha=1;
    // Below/right of the welcome panel: the head can be discovered in the app,
    // not only in a scene-only preview. The canyon still occludes its tail.
    ctx.save();ctx.translate(32,24);leviathan(p);ctx.restore();p.color="";
    // Distant canyon walls occlude the animal's tail. Nothing from the ruined
    // shelf or near organisms should accidentally be painted behind them.
    p.poly([[0,103],[24,120],[27,144],[50,152],[56,175],[84,186],[106,205],
            [151,225],[174,270],[0,270]],"#0d2431");
    p.poly([[0,125],[22,147],[27,176],[53,180],[65,204],[95,216],[120,248],[0,270]],"#13313a");
    p.poly([[480,80],[453,96],[449,121],[430,137],[431,169],[409,187],
            [414,218],[398,242],[480,270]],"#0b202c");
    p.poly([[480,107],[461,128],[458,155],[443,163],[437,188],[421,208],[433,223],[480,238]],"#102c37");
    p.line(452,128,450,143,"#16353e");p.line(445,165,440,180,"#1a3942");
    // Rock shelves, a dark centre trench, and bedding planes with varying depth.
    p.poly(FLOOR.concat([[480,270],[0,270]]),"#193239");
    p.poly([[0,202],[31,204],[43,215],[72,216],[92,233],[115,240],[99,254],[51,247],[0,244]],"#22414a");
    p.poly([[0,202],[31,204],[43,215],[72,216],[88,230],[63,227],[38,224],[29,214],[0,212]],"#35535b");
    p.poly([[85,234],[110,240],[99,253],[118,266],[171,270],[96,270],[74,245]],"#102831");
    p.poly([[159,260],[191,264],[232,269],[281,259],[306,264],[319,270],[158,270]],"#081c25");
    p.poly([[295,255],[322,249],[348,234],[372,229],[397,225],[433,234],[480,229],[480,270],[347,264]],"#173239");
    for(var bed=0;bed<36;bed++) {
        var bx=P.hash(bed*17+443)*480,by=ground(bx)+P.hash(bed+709)*12;
        p.line(bx,by,bx+4+P.hash(bed)*10,by-1,bed%3===0?"#29444b":"#112a33");
    }
    temple(p,f);
    // Hydrothermal chimneys on the left shelf, with mineral-lit shoulders.
    for(var vent=0;vent<3;vent++) {
        var vx=58+vent*8,base=228+vent*3,h=18-vent*4;
        p.poly([[vx-3,base],[vx-2,base-h],[vx+1,base-h-2],[vx+3,base],[vx+1,base+1]],"#263b43");
        p.line(vx-2,base-h+1,vx,base-h-1,"#66817d");p.line(vx,base-h,vx+2,base-1,"#36555a");
        for(var bubble=0;bubble<4;bubble++) {
            var yy=base-h-6-bubble*6+[0,1,0,-1][f];
            p.dot(vx+(bubble%2),yy,"#284e59");p.dot(vx+1+(bubble%2),yy-1,"#386470");
        }
    }
    // Glass sponge gardens replace the bulky coral clumps. Different heights
    // follow the shelves; hollow centres leave the water visible through them.
    glassSponge(p,26,214,28,7);glassSponge(p,45,224,18,5);
    glassSponge(p,13,236,14,4);glassSponge(p,50,237,10,4);
    glassSponge(p,436,239,30,8);glassSponge(p,457,237,20,6);
    glassSponge(p,416,247,13,4);
    // Soft fronds come forward from the bottom corners and rocky cracks.
    frond(p,9,267,44,f,1);frond(p,21,267,31,f,2);frond(p,76,259,24,f,4);
    frond(p,469,265,46,f,3);frond(p,455,266,31,f,5);frond(p,434,254,19,f,2);
    // Tubeworms, an anemone and a segmented isopod reward a closer look.
    for(var worm=0;worm<5;worm++) {
        var wx=101+worm*3,wy=250+worm%2*2;
        p.line(wx,wy,wx+1,wy-5,"#537172");p.rect(wx,wy-6,3,1,"#866d7e");
    }
    for(var arm=0;arm<7;arm++) {
        var angle=arm*Math.PI*2/7;
        p.line(293,258,293+Math.cos(angle)*5,258+Math.sin(angle)*3,"#50757a");
        p.dot(293+Math.cos(angle)*5,258+Math.sin(angle)*3,"#779b9a");
    }
    p.ellipse(180,264,6,3,"#384953");
    for(var segment=0;segment<4;segment++) {
        p.line(177+segment*2,262,177+segment*2,265,"#172f3b");p.dot(177+segment*2,267,"#4a636c");
    }
    p.line(174,264,171,261,"#48646d");
    // Tiny exploratory gear and a fossil at the edge of the trench.
    p.rect(329,246,8,4,"#36515c");p.rect(331,245,4,1,"#6d8289");
    p.dot(334,247,"#91ada5");p.line(330,249,327,254,"#1b3542");
    strand(p,[[274,256],[270,252],[265,251],[260,252],[257,255]],"#35505a");
    for(var rib=0;rib<4;rib++) p.line(259+rib*4,253,260+rib*4,257,"#405b62");
    shark(p,191,117,29,"#183441",true);
    shark(p,299,176,19,"#102a36",false);
    // A small vampire squid, its cloak opened above the left escarpment.
    var mantleY=154+[0,0,1,0][f];
    glow(p,73,mantleY+1,7,8,"#624be2",0.12);
    p.poly([[69,mantleY-5],[73,mantleY-9],[77,mantleY-4],[81,mantleY],
            [76,mantleY+5],[69,mantleY+5],[65,mantleY]],"#283047");
    p.poly([[71,mantleY-5],[74,mantleY-7],[76,mantleY],[72,mantleY+3]],"#3b3c55");
    p.dot(71,mantleY-1,"#d2bdff");
    for(var tentacle=0;tentacle<4;tentacle++) {
        var tx=69+tentacle*2;
        strand(p,[[tx,mantleY+3],[tx-1,mantleY+8],
                  [tx+[0,1,0,-1][(f+tentacle)%4],mantleY+11]],"#35405c");
        p.dot(tx-1,mantleY+7,"#8571da");
    }
    // One pinprick of living light belongs to an angler near the trench floor.
    p.ellipse(211,240,4,3,"#172b3a");
    p.poly([[208,240],[205,237],[205,243]],"#172b3a");
    strand(p,[[213,238],[214,233],[217,232],[218,234]],"#304653");
    glow(p,218,235,3,3,"#278ced",0.16);
    p.dot(218,235,["#76d9ff","#8cebff","#b9ffff","#8cebff"][f]);
    p.dot(213,239,"#526b79");
    // Lanternfish form a loose school rather than an evenly spaced particle grid.
    for(var fish=0;fish<8;fish++) {
        var fx=146+P.hash(fish*17+391)*60,fy=166+P.hash(fish*11+877)*20;
        if(fish%3===0) glow(p,fx+1,fy,3,2,"#28b8d9",0.09);
        p.line(fx-2,fy,fx+2,fy,"#32728a");p.dot(fx+2,fy,"#8cebe5");
        p.dot(fx-3,fy+(fish%2===0?1:-1),"#203e4d");
    }
    jelly(p,49,69,7,f,false);jelly(p,264,213,5,(f+2)%4,true);
    jelly(p,316,43,3,(f+1)%4,true);
    submersible(p,f);
    // Marine snow is very sparse. It only moves by a pixel within a four-frame
    // loop, so the abyss doesn't turn into another busy particle simulation.
    for(var mote=0;mote<115;mote++) {
        var mx=P.hash(mote*13+847)*480,my=P.hash(mote*7+193)*270;
        var illuminated=my>90 && my<216 && Math.abs(mx-(120+(my-83)*0.53))<(my-83)*0.30;
        var color=illuminated?"#375c65":"#16343f";
        p.dot(mx+[0,1,0,-1][(f+mote)%4],my,color);
    }
}
